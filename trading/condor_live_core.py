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
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from nifty_iron_condor_backtest import leg_charges

IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)
EXCHANGE = "NFO"
ORDER_POLL_INTERVAL_S = 1.0
ORDER_FILL_TIMEOUT_S = 30.0

logger = logging.getLogger("condor_live")


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
            raise RuntimeError(f"Order {order_id} ({tradingsymbol}) ended in status={last['status']}: {last.get('status_message')}")
        time_module.sleep(ORDER_POLL_INTERVAL_S)

    kite.cancel_order(variety=kite.VARIETY_REGULAR, order_id=order_id)
    raise RuntimeError(f"Order {order_id} ({tradingsymbol}) failed to fill in {ORDER_FILL_TIMEOUT_S:.0f}s; cancelled, manual check needed.")


def position_mtm(kite, state: CondorState) -> float:
    """Unrealized P&L in rupees for the whole position (one batched LTP call)."""
    ltps = get_ltps(kite, [leg["tradingsymbol"] for leg in state.legs])
    return sum(
        (ltps[leg["tradingsymbol"]] - leg["entry_price"]) * (1 if leg["is_buy"] else -1) * state.qty
        for leg in state.legs
    )


def stop_threshold(state: CondorState, credit_multiple: float | None, rupee_cap: float | None) -> float | None:
    """The MTM level (negative rupees) that triggers an exit; the tighter rule wins."""
    levels = []
    if credit_multiple is not None:
        levels.append(-abs(credit_multiple) * state.net_credit * state.qty)
    if rupee_cap is not None:
        levels.append(-abs(rupee_cap))
    return max(levels) if levels else None


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
    """Close all legs (shorts first -- they carry the uncapped side), record the
    round trip in history, clear state. Returns net P&L in rupees."""
    gross = charges = 0.0
    for leg in sorted(state.legs, key=lambda l: l["is_buy"]):  # False (short) sorts first
        _, fill = place_and_wait(kite, leg["tradingsymbol"], not leg["is_buy"], state.qty, dry_run)
        sign = 1 if leg["is_buy"] else -1
        gross += (fill - leg["entry_price"]) * sign * state.qty
        charges += leg_charges(leg["entry_price"], state.qty, leg["is_buy"]) + leg_charges(fill, state.qty, leg["is_buy"])

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
