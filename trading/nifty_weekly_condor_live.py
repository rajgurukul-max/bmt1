"""Live weekly Nifty Iron Condor -- PLACES REAL ORDERS.

Recommended configuration (from backtesting on 2 years of real NSE settlement
data, see nifty_iron_condor_backtest.py):
  - Enter Friday: sell CE 200 pts above CMP, buy CE 400 pts above CMP,
                  sell PE 200 pts below CMP, buy PE 400 pts below CMP.
  - Exit at the first close (checked once/day) where mark-to-market loss
    reaches 1.0x the net credit collected at entry (mid-week stop-loss).
  - Otherwise hold to the following Tuesday's expiry and close there.
  - 5 lots. Product NRML (this position spans multiple days -- MIS would
    force a same-day square-off and is wrong here).

Unlike live_trader.py (tick-by-tick intraday candles), this strategy only
needs ONE decision per day: has today's action (enter / check-stop / exit)
happened yet? So this script is a short-lived, idempotent job meant to be
run once a day (via cron) shortly before market close, rather than a
long-running process. State is persisted to disk (STATE_FILE) so the
position survives restarts across the multi-day hold -- critical since this
position lives across a weekend and the VPS could reboot in between.

Usage (see the bottom of this docstring for the recommended cron setup):
    python nifty_weekly_condor_live.py                  # auto: act on today's weekday
    python nifty_weekly_condor_live.py --dry-run         # log intended orders only
    python nifty_weekly_condor_live.py --action enter --dry-run   # force a specific
    python nifty_weekly_condor_live.py --action check --dry-run   # action, for testing
    python nifty_weekly_condor_live.py --action exit --dry-run    # regardless of weekday

Recommended cron (run once daily at 15:15 IST, well before the 15:30 close,
on every weekday -- the script itself decides whether there's anything to do):
    15 15 * * 1-5  cd /path/to/trading && /path/to/venv/bin/python nifty_weekly_condor_live.py >> logs/nifty_condor_cron.log 2>&1

Safety:
  - Refuses to enter a new position if state.json already shows one open.
  - Refuses to skip an open position that's past its expiry date without
    exiting it (always tries to flatten first).
  - --dry-run logs every order it would place without calling kite.place_order.
  - A manual `touch KILL_SWITCH` in this directory blocks new entries (does
    NOT auto-flatten an existing multi-day position, since that requires a
    judgment call this script shouldn't make unattended -- exit manually via
    `--action exit` if you want it flattened immediately).
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import time as time_module
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from config import BASE_DIR, load_config
from data import get_kite_client
from nifty_iron_condor_backtest import leg_charges

logger = logging.getLogger("nifty_weekly_condor")

STATE_FILE = BASE_DIR / "nifty_condor_state.json"
HISTORY_FILE = BASE_DIR / "logs" / "nifty_condor_history.csv"
KILL_SWITCH_FILE = BASE_DIR / "KILL_SWITCH"

# --- Recommended configuration (see module docstring) -----------------------
SHORT_OFFSET = 200
LONG_OFFSET = 400
LOTS = 5
STOP_LOSS_CREDIT_MULTIPLE = 1.0
ENTRY_WEEKDAY = 4  # Friday (0=Monday .. 4=Friday)
INDEX_SYMBOL = "NIFTY 50"
INDEX_EXCHANGE = "NSE"
FNO_NAME = "NIFTY"
FNO_EXCHANGE = "NFO"

ORDER_POLL_INTERVAL_S = 1.0
ORDER_FILL_TIMEOUT_S = 30.0


# --- state -------------------------------------------------------------------
@dataclass
class Leg:
    name: str          # sell_ce / buy_ce / sell_pe / buy_pe
    opt_type: str       # CE / PE
    strike: float
    tradingsymbol: str
    is_buy: bool
    entry_price: float | None = None


@dataclass
class CondorState:
    status: str          # "open" or "closed"
    entry_date: str
    expiry: str
    lot_size: int
    qty: int             # lot_size * LOTS
    net_credit: float    # per-share, at entry
    legs: list           # list[dict] matching Leg fields


def _state_path(dry_run: bool) -> Path:
    # A dry run must NEVER touch the real state file: doing so would either block
    # a subsequent real entry (enter_position refuses if state exists) or make a
    # later real check/exit act on fake dry-run fill prices. Fully separate file.
    return STATE_FILE.with_suffix(".dryrun.json") if dry_run else STATE_FILE


def _history_path(dry_run: bool) -> Path:
    return HISTORY_FILE.with_suffix(".dryrun.csv") if dry_run else HISTORY_FILE


def load_state(dry_run: bool = False) -> CondorState | None:
    path = _state_path(dry_run)
    if not path.exists():
        return None
    with open(path) as fh:
        data = json.load(fh)
    return CondorState(**data)


def save_state(state: CondorState, dry_run: bool = False) -> None:
    with open(_state_path(dry_run), "w") as fh:
        json.dump(asdict(state), fh, indent=2)


def clear_state(dry_run: bool = False) -> None:
    path = _state_path(dry_run)
    if path.exists():
        path.unlink()


def append_history(row: dict, dry_run: bool = False) -> None:
    path = _history_path(dry_run)
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    with open(path, "a", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(row.keys()))
        if is_new:
            writer.writeheader()
        writer.writerow(row)


# --- market data / instrument lookup -----------------------------------------
def get_cmp(kite) -> float:
    return kite.ltp([f"{INDEX_EXCHANGE}:{INDEX_SYMBOL}"])[f"{INDEX_EXCHANGE}:{INDEX_SYMBOL}"]["last_price"]


def nearest_strike(strikes: list[float], target: float) -> float:
    return min(strikes, key=lambda s: abs(s - target))


def get_week_instruments(kite, min_expiry: date) -> tuple[list[dict], date]:
    """Returns (instruments for the nearest weekly expiry > min_expiry, that expiry)."""
    instruments = kite.instruments(FNO_EXCHANGE)
    nifty_opts = [i for i in instruments if i["name"] == FNO_NAME and i["segment"] == "NFO-OPT"]
    expiries = sorted(set(i["expiry"] for i in nifty_opts if i["expiry"] > min_expiry))
    if not expiries:
        raise RuntimeError("No future NIFTY option expiries found.")
    expiry = expiries[0]
    return [i for i in nifty_opts if i["expiry"] == expiry], expiry


def find_symbol(instruments: list[dict], strike: float, opt_type: str) -> str:
    for i in instruments:
        if i["strike"] == strike and i["instrument_type"] == opt_type:
            return i["tradingsymbol"]
    raise RuntimeError(f"No instrument found for strike={strike} type={opt_type}")


def get_ltp(kite, tradingsymbol: str) -> float:
    key = f"{FNO_EXCHANGE}:{tradingsymbol}"
    return kite.ltp([key])[key]["last_price"]


# --- order placement ----------------------------------------------------------
def place_and_wait(kite, tradingsymbol: str, is_buy: bool, qty: int, dry_run: bool) -> tuple[str | None, float]:
    ltp = get_ltp(kite, tradingsymbol)
    buffer_pct = 0.02
    buffer = max(ltp * buffer_pct, 0.05)
    limit_price = round((ltp + buffer if is_buy else max(ltp - buffer, 0.05)) / 0.05) * 0.05
    transaction_type = kite.TRANSACTION_TYPE_BUY if is_buy else kite.TRANSACTION_TYPE_SELL

    if dry_run:
        logger.warning("[DRY RUN] Would place %s %s qty=%d limit=%.2f (ltp=%.2f)",
                        transaction_type, tradingsymbol, qty, limit_price, ltp)
        return None, limit_price

    order_id = kite.place_order(
        variety=kite.VARIETY_REGULAR, exchange=FNO_EXCHANGE, tradingsymbol=tradingsymbol,
        transaction_type=transaction_type, quantity=qty, product=kite.PRODUCT_NRML,
        order_type=kite.ORDER_TYPE_LIMIT, price=limit_price,
    )
    logger.info("Placed order_id=%s %s %s qty=%d limit=%.2f", order_id, transaction_type, tradingsymbol, qty, limit_price)

    deadline = time_module.monotonic() + ORDER_FILL_TIMEOUT_S
    while time_module.monotonic() < deadline:
        history = kite.order_history(order_id)
        last = history[-1]
        if last["status"] == "COMPLETE":
            avg_price = float(last["average_price"])
            logger.info("Order %s COMPLETE avg_price=%.2f", order_id, avg_price)
            return order_id, avg_price
        if last["status"] in ("REJECTED", "CANCELLED"):
            raise RuntimeError(f"Order {order_id} ({tradingsymbol}) ended in status={last['status']}: {last.get('status_message')}")
        time_module.sleep(ORDER_POLL_INTERVAL_S)

    kite.cancel_order(variety=kite.VARIETY_REGULAR, order_id=order_id)
    raise RuntimeError(f"Order {order_id} ({tradingsymbol}) failed to fill in {ORDER_FILL_TIMEOUT_S:.0f}s; cancelled, manual check needed.")


# --- strategy actions ----------------------------------------------------------
def enter_position(kite, dry_run: bool) -> None:
    if load_state(dry_run) is not None:
        raise RuntimeError("A position is already open (state file exists) -- refusing to enter another one.")
    if KILL_SWITCH_FILE.exists():
        logger.warning("KILL_SWITCH present -- skipping entry today.")
        return

    today = date.today()
    instruments, expiry = get_week_instruments(kite, min_expiry=today)
    cmp_ = get_cmp(kite)
    lot_size = instruments[0]["lot_size"]
    qty = lot_size * LOTS

    ce_strikes = sorted(set(i["strike"] for i in instruments if i["instrument_type"] == "CE"))
    pe_strikes = sorted(set(i["strike"] for i in instruments if i["instrument_type"] == "PE"))

    legs = [
        Leg("buy_ce", "CE", nearest_strike(ce_strikes, cmp_ + LONG_OFFSET), "", True),
        Leg("buy_pe", "PE", nearest_strike(pe_strikes, cmp_ - LONG_OFFSET), "", True),
        Leg("sell_ce", "CE", nearest_strike(ce_strikes, cmp_ + SHORT_OFFSET), "", False),
        Leg("sell_pe", "PE", nearest_strike(pe_strikes, cmp_ - SHORT_OFFSET), "", False),
    ]
    # Buy the protective wings FIRST so the position is never naked mid-entry.
    for leg in legs:
        leg.tradingsymbol = find_symbol(instruments, leg.strike, leg.opt_type)
        _, fill = place_and_wait(kite, leg.tradingsymbol, leg.is_buy, qty, dry_run)
        leg.entry_price = fill

    by_name = {l.name: l for l in legs}
    net_credit = (
        by_name["sell_ce"].entry_price + by_name["sell_pe"].entry_price
        - by_name["buy_ce"].entry_price - by_name["buy_pe"].entry_price
    )

    state = CondorState(
        status="open", entry_date=today.isoformat(), expiry=expiry.isoformat(),
        lot_size=lot_size, qty=qty, net_credit=net_credit,
        legs=[asdict(l) for l in legs],
    )
    save_state(state, dry_run)
    logger.info(
        "ENTERED condor: CMP=%.2f expiry=%s legs=%s net_credit/share=%.2f (qty=%d)%s",
        cmp_, expiry, {l.name: l.strike for l in legs}, net_credit, qty,
        " [DRY RUN state]" if dry_run else "",
    )


def _mark_to_market(kite, state: CondorState) -> float:
    """Current unrealized P&L in rupees for the whole position."""
    mtm = 0.0
    for leg in state.legs:
        ltp = get_ltp(kite, leg["tradingsymbol"])
        sign = 1 if leg["is_buy"] else -1
        mtm += (ltp - leg["entry_price"]) * sign * state.qty
    return mtm


def check_and_maybe_stop(kite, dry_run: bool) -> None:
    state = load_state(dry_run)
    if state is None or state.status != "open":
        logger.info("No open position to check.")
        return

    mtm = _mark_to_market(kite, state)
    stop_threshold = -abs(STOP_LOSS_CREDIT_MULTIPLE) * state.net_credit * state.qty
    logger.info("Mid-week check: MTM=Rs %.2f  stop_threshold=Rs %.2f", mtm, stop_threshold)

    if mtm <= stop_threshold:
        logger.warning("Stop-loss triggered (MTM %.2f <= threshold %.2f). Exiting.", mtm, stop_threshold)
        exit_position(kite, "stop_loss", dry_run)
    else:
        logger.info("Within threshold, holding position.")


def exit_position(kite, reason: str, dry_run: bool) -> None:
    state = load_state(dry_run)
    if state is None or state.status != "open":
        logger.info("No open position to exit.")
        return

    # Close the SHORT legs first (removes the naked/uncapped-risk side first),
    # then the long legs.
    legs_sorted = sorted(state.legs, key=lambda l: l["is_buy"])  # False (short) before True (long)

    gross = 0.0
    charges = 0.0
    exit_prices = {}
    for leg in legs_sorted:
        closing_is_buy = not leg["is_buy"]  # closing a short = buy, closing a long = sell
        _, fill = place_and_wait(kite, leg["tradingsymbol"], closing_is_buy, state.qty, dry_run)
        exit_prices[leg["name"]] = fill
        sign = 1 if leg["is_buy"] else -1
        gross += (fill - leg["entry_price"]) * sign * state.qty
        charges += (
            leg_charges(leg["entry_price"], state.qty, leg["is_buy"])
            + leg_charges(fill, state.qty, leg["is_buy"])
        )

    net_pnl = gross - charges
    logger.info("EXITED condor (%s): gross=Rs %.2f charges=Rs %.2f net=Rs %.2f", reason, gross, charges, net_pnl)

    append_history({
        "entry_date": state.entry_date, "expiry": state.expiry, "exit_date": date.today().isoformat(),
        "exit_reason": reason, "net_credit_per_share": state.net_credit, "qty": state.qty,
        "gross_pnl": round(gross, 2), "charges": round(charges, 2), "net_pnl": round(net_pnl, 2),
    }, dry_run)
    clear_state(dry_run)


# --- entry point ----------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Log intended orders without placing them.")
    parser.add_argument("--action", choices=["auto", "enter", "check", "exit"], default="auto",
                         help="Force a specific action regardless of today's weekday (for testing).")
    args = parser.parse_args()

    cfg = load_config()
    cfg.logging.log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(cfg.logging.log_dir / f"nifty_condor_{date.today().isoformat()}.log"),
        ],
    )

    kite = get_kite_client(cfg)
    today = date.today()
    state = load_state()

    if args.action != "auto":
        {"enter": enter_position, "check": lambda k, d: check_and_maybe_stop(k, d),
         "exit": lambda k, d: exit_position(k, "manual", d)}[args.action](kite, args.dry_run)
        return

    if state is not None and state.status == "open":
        expiry = date.fromisoformat(state.expiry)
        if today >= expiry:
            logger.info("Today (%s) is at/past expiry (%s) -- exiting.", today, expiry)
            exit_position(kite, "expiry", args.dry_run)
        elif today > date.fromisoformat(state.entry_date):
            logger.info("Mid-week check for position opened %s.", state.entry_date)
            check_and_maybe_stop(kite, args.dry_run)
        else:
            logger.info("Position opened today already -- nothing to do.")
    else:
        if today.weekday() == ENTRY_WEEKDAY:
            logger.info("Today is the configured entry day (weekday=%d) -- entering.", ENTRY_WEEKDAY)
            enter_position(kite, args.dry_run)
        else:
            logger.info("No open position and today is not the entry day -- nothing to do.")


if __name__ == "__main__":
    main()
