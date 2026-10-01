"""Shared pieces for the live iron condor scripts: persisted position state,
order placement, mark-to-market, and the intraday stop monitor.

The stop is checked every minute during market hours (expiry day included),
not once at the close: close-only checks let stopped trades overshoot badly in
backtests (BankNifty stop-outs realized Rs 30-58k on a Rs 25k limit, and
Nifty's largest losses all happened on expiry day, where no close check ran).

Standalone use -- a READ-ONLY logger for an already-open position (never
places orders), e.g. to see whether a loss cap would have triggered:
    python condor_live_core.py nifty_condor_state.dryrun.json --until 15:14 \\
        --credit-multiple 1.0 --rupee-cap 25000
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import time as time_module
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from nifty_iron_condor_backtest import leg_charges

HOLIDAYS_FILE = Path(__file__).resolve().parent / "nse_holidays.txt"
IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)
EXCHANGE = "NFO"
ORDER_POLL_INTERVAL_S = 1.0
ORDER_FILL_TIMEOUT_S = 30.0
EXIT_ATTEMPTS = 3          # re-priced retries per leg when closing

logger = logging.getLogger("condor_live")


@dataclass
class Leg:
    name: str          # sell_ce / buy_ce / sell_pe / buy_pe
    opt_type: str       # CE / PE
    strike: float
    tradingsymbol: str
    is_buy: bool
    entry_price: float | None = None
    qty: int | None = None   # only set when it differs from the position's qty (a partial fill)


@dataclass
class CondorState:
    status: str          # "open"
    entry_date: str
    expiry: str
    lot_size: int
    qty: int             # lot_size * lots
    net_credit: float    # per-share, at entry
    legs: list           # list[dict] matching Leg fields


def now_ist() -> datetime:
    return datetime.now(IST)


def parse_hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def load_holidays(path: Path = HOLIDAYS_FILE) -> set[date]:
    if not path.exists():
        return set()
    out = set()
    for line in path.read_text().splitlines():
        token = line.split("#", 1)[0].strip()
        if token:
            out.add(date.fromisoformat(token))
    return out


def is_trading_day(d: date, holidays: set[date]) -> bool:
    return d.weekday() < 5 and d not in holidays


def is_last_trading_day_through(d: date, weekday: int, holidays: set[date]) -> bool:
    """True if d is a trading day and every day after it up to `weekday` of the
    same week is not -- e.g. with weekday=4, Friday normally, or Thursday when
    Friday is a holiday."""
    if not is_trading_day(d, holidays) or d.weekday() > weekday:
        return False
    return not any(
        is_trading_day(d + timedelta(days=k), holidays) for k in range(1, weekday - d.weekday() + 1)
    )


def dry_path(path: Path, dry_run: bool) -> Path:
    # A dry run must never touch the real files: a fake dry-run position would
    # block a real entry, or a real exit would act on fake fill prices.
    return path.with_name(f"{path.stem}.dryrun{path.suffix}") if dry_run else path


# --- persisted state ------------------------------------------------------------
def load_state(path: Path) -> CondorState | None:
    if not path.exists():
        return None
    with open(path) as fh:
        return CondorState(**json.load(fh))


def save_state(state: CondorState, path: Path) -> None:
    with open(path, "w") as fh:
        json.dump(asdict(state), fh, indent=2)


def clear_state(path: Path) -> None:
    if path.exists():
        path.unlink()


def append_csv(row: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    with open(path, "a", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(row.keys()))
        if is_new:
            writer.writeheader()
        writer.writerow(row)


def read_history(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


# --- market data / orders -------------------------------------------------------
def nearest_strike(strikes: list[float], target: float) -> float:
    return min(strikes, key=lambda s: abs(s - target))


def get_ltps(kite, tradingsymbols: list[str]) -> dict[str, float]:
    keys = [f"{EXCHANGE}:{s}" for s in tradingsymbols]
    quotes = kite.ltp(keys)
    return {s: quotes[k]["last_price"] for s, k in zip(tradingsymbols, keys)}


class OrderNotFilled(RuntimeError):
    """An order ended without filling completely. `filled_qty` (possibly 0)
    at `avg_price` DID trade and is now a real position the caller must track."""

    def __init__(self, msg: str, filled_qty: int = 0, avg_price: float = 0.0):
        super().__init__(msg)
        self.filled_qty = filled_qty
        self.avg_price = avg_price


def _not_filled(order_id: str, tradingsymbol: str, last: dict, why: str) -> OrderNotFilled:
    filled = int(last.get("filled_quantity") or 0)
    avg = float(last.get("average_price") or 0.0)
    return OrderNotFilled(f"Order {order_id} ({tradingsymbol}) {why}; filled {filled} @ {avg:.2f}: "
                          f"{last.get('status_message')}", filled, avg)


def place_and_wait(kite, tradingsymbol: str, is_buy: bool, qty: int, dry_run: bool) -> tuple[str | None, float]:
    ltp = get_ltps(kite, [tradingsymbol])[tradingsymbol]
    buffer = max(ltp * 0.02, 0.05)
    limit_price = round((ltp + buffer if is_buy else max(ltp - buffer, 0.05)) / 0.05) * 0.05
    transaction_type = kite.TRANSACTION_TYPE_BUY if is_buy else kite.TRANSACTION_TYPE_SELL

    if dry_run:
        logger.warning("[DRY RUN] Would place %s %s qty=%d limit=%.2f (ltp=%.2f)",
                       transaction_type, tradingsymbol, qty, limit_price, ltp)
        return None, limit_price

    order_id = kite.place_order(
        variety=kite.VARIETY_REGULAR, exchange=EXCHANGE, tradingsymbol=tradingsymbol,
        transaction_type=transaction_type, quantity=qty, product=kite.PRODUCT_NRML,
        order_type=kite.ORDER_TYPE_LIMIT, price=limit_price,
    )
    logger.info("Placed order_id=%s %s %s qty=%d limit=%.2f", order_id, transaction_type, tradingsymbol, qty, limit_price)

    deadline = time_module.monotonic() + ORDER_FILL_TIMEOUT_S
    while time_module.monotonic() < deadline:
        last = kite.order_history(order_id)[-1]
        if last["status"] == "COMPLETE":
            avg_price = float(last["average_price"])
            logger.info("Order %s COMPLETE avg_price=%.2f", order_id, avg_price)
            return order_id, avg_price
        if last["status"] in ("REJECTED", "CANCELLED"):
            raise _not_filled(order_id, tradingsymbol, last, f"ended in status={last['status']}")
        time_module.sleep(ORDER_POLL_INTERVAL_S)

    # Not filled in time: cancel, then read the final state -- part of the
    # quantity may have traded, or the whole order may fill while cancelling.
    try:
        kite.cancel_order(variety=kite.VARIETY_REGULAR, order_id=order_id)
    except Exception as exc:
        logger.warning("Cancel of order %s failed (%s) -- it may have just filled.", order_id, exc)
    for _ in range(10):
        last = kite.order_history(order_id)[-1]
        if last["status"] == "COMPLETE":
            avg_price = float(last["average_price"])
            logger.info("Order %s COMPLETE (while cancelling) avg_price=%.2f", order_id, avg_price)
            return order_id, avg_price
        if last["status"] in ("REJECTED", "CANCELLED"):
            break
        time_module.sleep(ORDER_POLL_INTERVAL_S)
    else:
        logger.critical("Order %s (%s) still %s after cancel -- CHECK THE ORDERS TAB, its fill may change.",
                        order_id, tradingsymbol, last["status"])
    raise _not_filled(order_id, tradingsymbol, last, f"not filled in {ORDER_FILL_TIMEOUT_S:.0f}s, cancelled")


def leg_qty(state: CondorState, leg: dict) -> int:
    return leg.get("qty") or state.qty


def position_mtm(kite, state: CondorState) -> float:
    """P&L in rupees for the whole position (one batched LTP call). Quantity
    already closed during an interrupted exit counts at its actual fill price."""
    open_symbols = [leg["tradingsymbol"] for leg in state.legs if leg.get("exit_price") is None]
    ltps = get_ltps(kite, open_symbols) if open_symbols else {}
    total = 0.0
    for leg in state.legs:
        q, sign = leg_qty(state, leg), (1 if leg["is_buy"] else -1)
        if leg.get("exit_price") is not None:
            total += (leg["exit_price"] - leg["entry_price"]) * sign * q
        else:
            closed = leg.get("closed_qty", 0)
            total += ((leg.get("exit_value", 0.0) - leg["entry_price"] * closed)
                      + (ltps[leg["tradingsymbol"]] - leg["entry_price"]) * (q - closed)) * sign
    return total


class EntryAborted(RuntimeError):
    pass


def enter_condor(kite, legs: list[Leg], qty: int, lot_size: int, expiry: date, dry_run: bool,
                 state_path: Path, history_path: Path, label: str) -> CondorState:
    """Margin-check, then fill legs in the given order (wings first). If any leg
    fails after others filled -- including a leg that filled only partly --
    everything that traded is unwound immediately, shorts first, so no
    untracked position is left behind. If the unwind itself fails, the wings
    are kept (they still cover any short left open) and the state file holds
    exactly what is still open for --action exit to finish."""
    orders = [dict(exchange=EXCHANGE, tradingsymbol=l.tradingsymbol, variety="regular", product="NRML",
                   order_type="MARKET", quantity=qty,
                   transaction_type=kite.TRANSACTION_TYPE_BUY if l.is_buy else kite.TRANSACTION_TYPE_SELL)
              for l in legs]
    required = kite.basket_order_margins(orders)["final"]["total"]
    available = kite.margins(segment="equity")["net"]
    logger.info("%s margin check: required Rs %.0f, available Rs %.0f", label, required, available)
    if required > available:
        msg = f"{label}: insufficient funds (need Rs {required:,.0f}, have Rs {available:,.0f}) -- not entering."
        if not dry_run:
            raise EntryAborted(msg)
        logger.warning("[DRY RUN] %s", msg)

    filled: list[Leg] = []
    try:
        for leg in legs:
            _, leg.entry_price = place_and_wait(kite, leg.tradingsymbol, leg.is_buy, qty, dry_run)
            filled.append(leg)
    except Exception as exc:
        logger.critical("%s entry failed on %s after %d leg(s) filled: %s -- unwinding.",
                        label, leg.tradingsymbol, len(filled), exc)
        part_qty = getattr(exc, "filled_qty", 0)
        if part_qty:
            logger.critical("%s: %d of %d filled on %s before the order died -- unwinding that too.",
                            label, part_qty, qty, leg.tradingsymbol)
            filled.append(Leg(leg.name, leg.opt_type, leg.strike, leg.tradingsymbol, leg.is_buy,
                              exc.avg_price, part_qty))
        if filled:
            partial = CondorState("open", now_ist().date().isoformat(), expiry.isoformat(), lot_size, qty,
                                  sum(l.entry_price * (-1 if l.is_buy else 1) * (l.qty or qty) for l in filled) / qty,
                                  [asdict(l) for l in filled])
            save_state(partial, state_path)
            try:
                exit_position(kite, partial, "entry_failed_unwind", dry_run, state_path, history_path)
            except Exception as unwind_exc:
                logger.critical("%s UNWIND FAILED (%s). MANUAL ACTION: check Positions; %s lists what is "
                                "still open and `--action exit` closes only that.", label, unwind_exc, state_path)
                raise EntryAborted(f"{label} entry aborted and unwind failed: {unwind_exc}") from exc
        raise EntryAborted(f"{label} entry aborted: {exc}") from exc

    state = CondorState("open", now_ist().date().isoformat(), expiry.isoformat(), lot_size, qty,
                        sum(l.entry_price * (-1 if l.is_buy else 1) for l in legs), [asdict(l) for l in legs])
    save_state(state, state_path)
    return state


def stop_threshold(state: CondorState, credit_multiple: float | None, rupee_cap: float | None) -> float | None:
    """The MTM level (negative rupees) that triggers an exit; the tighter rule wins."""
    levels = []
    if credit_multiple is not None:
        levels.append(-abs(credit_multiple) * state.net_credit * state.qty)
    if rupee_cap is not None:
        levels.append(-abs(rupee_cap))
    return max(levels) if levels else None


def connect_when_token_valid(give_up: time = time(15, 20), retry_seconds: float = 60.0):
    """Kite client once .env holds a valid access token. The daily process
    starts before the morning login; crashing on a stale token would leave an
    open position with no stop watching it, so re-read .env and retry instead
    (auth.py rewrites .env, no restart needed)."""
    from dotenv import load_dotenv

    from config import BASE_DIR, load_config
    from data import get_kite_client

    while True:
        load_dotenv(BASE_DIR / ".env", override=True)
        try:
            kite = get_kite_client(load_config())
            kite.profile()
            return kite
        except Exception as exc:
            if now_ist().time() >= give_up:
                raise RuntimeError("No valid Kite token all day -- any open position was NOT monitored.") from exc
            logger.critical("Kite token not valid (%s). Log in now: python auth.py <request_token>. "
                            "Retrying every %.0fs -- the stop is NOT active until then.", exc, retry_seconds)
            time_module.sleep(retry_seconds)


# --- intraday monitor -------------------------------------------------------------
def monitor_until(kite, state: CondorState, threshold: float | None, until: time, log_path: Path,
                  poll_seconds: float = 60.0) -> tuple[str, float | None]:
    """Poll the position's MTM every `poll_seconds` during market hours until
    `until` (IST) or until MTM <= threshold. Returns ("stop", mtm) on a breach,
    ("time", last_mtm) when `until` is reached. Every poll is appended to
    log_path so each day's intraday path is kept for later review."""
    last_mtm = None
    while True:
        t = now_ist()
        if t.time() >= until or t.time() >= MARKET_CLOSE:
            return "time", last_mtm
        if t.time() < MARKET_OPEN:
            wait = (datetime.combine(t.date(), MARKET_OPEN, IST) - t).total_seconds()
            time_module.sleep(min(max(wait, 1.0), 60.0))
            continue
        try:
            mtm = position_mtm(kite, state)
        except Exception as exc:  # network / broker hiccup: keep watching, don't crash the stop
            logger.warning("MTM poll failed (%s) -- retrying in %.0fs", exc, poll_seconds)
            time_module.sleep(poll_seconds)
            continue
        last_mtm = mtm
        append_csv({
            "time_ist": t.strftime("%Y-%m-%d %H:%M:%S"), "mtm": round(mtm, 2),
            "threshold": None if threshold is None else round(threshold, 2),
        }, log_path)
        if threshold is not None and mtm <= threshold:
            logger.warning("STOP: MTM Rs %.2f <= threshold Rs %.2f at %s", mtm, threshold, t.strftime("%H:%M:%S"))
            return "stop", mtm
        time_module.sleep(poll_seconds)


def exit_position(kite, state: CondorState, reason: str, dry_run: bool, state_path: Path, history_path: Path) -> float:
    """Close all open legs (shorts first -- they carry the uncapped side), record
    the round trip in history, clear state. Returns net P&L in rupees. Every
    fill -- including part of an order -- is saved to the state file as soon as
    it is known, and an unfilled remainder is retried (re-priced) up to
    EXIT_ATTEMPTS times. A short that cannot be closed stops the exit before
    any wing is sold. A rerun closes only what is still open; it never
    re-trades quantity that is already flat."""
    for leg in sorted(state.legs, key=lambda l: l["is_buy"]):  # False (short) sorts first
        if leg.get("exit_price") is not None:
            continue
        q = leg_qty(state, leg)
        for attempt in range(1, EXIT_ATTEMPTS + 1):
            remaining = q - leg.get("closed_qty", 0)
            try:
                _, price = place_and_wait(kite, leg["tradingsymbol"], not leg["is_buy"], remaining, dry_run)
                got, err = remaining, None
            except OrderNotFilled as exc:
                got, price, err = exc.filled_qty, exc.avg_price, exc
            if got:
                leg["closed_qty"] = leg.get("closed_qty", 0) + got
                leg["exit_value"] = leg.get("exit_value", 0.0) + got * price
            if leg.get("closed_qty", 0) >= q:
                leg["exit_price"] = leg["exit_value"] / q
                save_state(state, state_path)
                break
            save_state(state, state_path)
            logger.critical("Closing %s: attempt %d/%d failed (%s); %d of %d still open.",
                            leg["tradingsymbol"], attempt, EXIT_ATTEMPTS, err, q - leg.get("closed_qty", 0), q)
        else:
            raise RuntimeError(
                f"Could not close {leg['tradingsymbol']}: {q - leg.get('closed_qty', 0)} of {q} still open after "
                f"{EXIT_ATTEMPTS} attempts. MANUAL ACTION: check Positions; rerun --action exit to close the rest.")

    gross = charges = 0.0
    for leg in state.legs:
        q, sign = leg_qty(state, leg), (1 if leg["is_buy"] else -1)
        gross += (leg["exit_price"] - leg["entry_price"]) * sign * q
        charges += (leg_charges(leg["entry_price"], q, leg["is_buy"])
                    + leg_charges(leg["exit_price"], q, leg["is_buy"]))

    net = gross - charges
    logger.info("EXITED condor (%s): gross=Rs %.2f charges=Rs %.2f net=Rs %.2f", reason, gross, charges, net)
    append_csv({
        "entry_date": state.entry_date, "expiry": state.expiry, "exit_date": now_ist().date().isoformat(),
        "exit_reason": reason, "net_credit_per_share": state.net_credit, "qty": state.qty,
        "gross_pnl": round(gross, 2), "charges": round(charges, 2), "net_pnl": round(net, 2),
    }, history_path)
    clear_state(state_path)
    return net


# --- standalone read-only logger ----------------------------------------------------
def main() -> None:
    from config import load_config
    from data import get_kite_client

    ap = argparse.ArgumentParser(description="Read-only intraday MTM logger for an open condor state file.")
    ap.add_argument("state_file")
    ap.add_argument("--until", default="15:29", help="HH:MM IST")
    ap.add_argument("--credit-multiple", type=float, default=None)
    ap.add_argument("--rupee-cap", type=float, default=None)
    ap.add_argument("--poll-seconds", type=float, default=60.0)
    ap.add_argument("--log", default=None, help="CSV path (default logs/<state>_intraday_<date>.csv)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout)])
    state = load_state(Path(args.state_file))
    if state is None:
        sys.exit(f"No open position in {args.state_file}")
    threshold = stop_threshold(state, args.credit_multiple, args.rupee_cap)
    log_path = Path(args.log) if args.log else Path("logs") / f"{Path(args.state_file).stem}_intraday_{now_ist().date()}.csv"
    kite = get_kite_client(load_config())
    logger.info("Watching %s until %s IST, threshold=%s, logging to %s", args.state_file, args.until, threshold, log_path)
    reason, mtm = monitor_until(kite, state, threshold, parse_hhmm(args.until), log_path, args.poll_seconds)
    if reason == "stop":
        logger.warning("WOULD HAVE STOPPED OUT (read-only mode, nothing placed): MTM Rs %.2f", mtm)
        # keep logging the rest of the session so the full intraday path is recorded
        monitor_until(kite, state, None, parse_hhmm(args.until), log_path, args.poll_seconds)
    logger.info("Done. Last MTM: %s", mtm)


if __name__ == "__main__":
    main()
