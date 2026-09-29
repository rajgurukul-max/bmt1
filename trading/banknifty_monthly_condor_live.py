"""Live monthly BankNifty Iron Condor -- PLACES REAL ORDERS unless --dry-run.

Configuration (banknifty_iron_condor_backtest.py / banknifty_sweep.py, 2 years
of real NSE settlement data: Rs 5.37L net on 5 lots, max drawdown -Rs 82k):
  - Sell CE/PE 1000 pts OTM, buy CE/PE 2500 pts OTM, 5 lots, product NRML.
  - Enter ~15 calendar days before the monthly expiry, at ENTRY_TIME.
  - Exit the whole position if its loss reaches Rs 25,000, checked EVERY
    MINUTE through the trading day (expiry day included) -- not once at the
    close, which let stopped trades overshoot to Rs 30-58k in the backtest.
  - Otherwise hold to expiry and close at EXPIRY_EXIT_TIME on expiry day.

Entry rule, live version: the first trading day on which the next expiry is
<= DAYS_BEFORE calendar days away, once per expiry. The backtest used the last
trading day >= 15 days out; the two differ only when day 15 is a weekend or
holiday (by a day or two, inside the 14-18 day range that backtested well),
and this way needs no holiday calendar.

Run ONE long-lived process per trading day, started before the open:
    10 9 * * 1-5  cd /path/to/trading && venv/bin/python banknifty_monthly_condor_live.py >> logs/banknifty_condor_cron.log 2>&1
It monitors any open position until 15:25 (exits at 15:15 on expiry day), and
on the entry day enters at ENTRY_TIME and monitors the rest of the session.

Manual actions (for testing / intervention):
    --action status | enter | monitor | exit      (add --dry-run to place nothing)
    --until HH:MM  --poll-seconds N              (monitor tuning)

Safety: refuses a second position while one is open; never re-enters an
expiry already traded (a stop-out stays out until next month); dry runs use
separate state/history files; `touch KILL_SWITCH` blocks new entries (an open
position keeps being monitored and stopped out as normal).
"""
from __future__ import annotations

import argparse
import logging
import sys
import time as time_module
from dataclasses import asdict
from datetime import date, datetime, time, timedelta

import condor_live_core as core
from config import BASE_DIR, load_config
from data import get_kite_client

logger = logging.getLogger("banknifty_monthly_condor")

STATE_FILE = BASE_DIR / "banknifty_condor_state.json"
HISTORY_FILE = BASE_DIR / "logs" / "banknifty_condor_history.csv"
KILL_SWITCH_FILE = BASE_DIR / "KILL_SWITCH"

SHORT_OFFSET = 1000
LONG_OFFSET = 2500
LOTS = 5
STOP_LOSS_RUPEES = 25000
DAYS_BEFORE = 15
MIN_DAYS_BEFORE = 10  # past this, the cycle's entry window is considered missed
ENTRY_TIME = time(15, 15)        # backtest entered at the close
MONITOR_END = time(15, 25)
EXPIRY_EXIT_TIME = time(15, 15)
INDEX_KEY = "NSE:NIFTY BANK"
FNO_NAME = "BANKNIFTY"


def paths(dry_run: bool):
    return core.dry_path(STATE_FILE, dry_run), core.dry_path(HISTORY_FILE, dry_run)


def intraday_log(dry_run: bool):
    return core.dry_path(BASE_DIR / "logs" / f"banknifty_condor_intraday_{core.now_ist().date()}.csv", dry_run)


def option_instruments(kite) -> list[dict]:
    return [i for i in kite.instruments(core.EXCHANGE) if i["name"] == FNO_NAME and i["segment"] == "NFO-OPT"]


def next_expiry(instruments: list[dict], today: date) -> date:
    return min(i["expiry"] for i in instruments if i["expiry"] > today)


def already_traded(expiry: date, dry_run: bool) -> bool:
    state_path, history_path = paths(dry_run)
    state = core.load_state(state_path)
    if state is not None and state.expiry == expiry.isoformat():
        return True
    return any(row["expiry"] == expiry.isoformat() for row in core.read_history(history_path))


def is_entry_day(kite, today: date, dry_run: bool) -> tuple[bool, date]:
    expiry = next_expiry(option_instruments(kite), today)
    days = (expiry - today).days
    return MIN_DAYS_BEFORE <= days <= DAYS_BEFORE and not already_traded(expiry, dry_run), expiry


def enter_position(kite, dry_run: bool) -> core.CondorState | None:
    state_path, _ = paths(dry_run)
    if core.load_state(state_path) is not None:
        raise RuntimeError("A position is already open -- refusing to enter another one.")
    if KILL_SWITCH_FILE.exists():
        logger.warning("KILL_SWITCH present -- skipping entry.")
        return None

    today = core.now_ist().date()
    instruments = option_instruments(kite)
    expiry = next_expiry(instruments, today)
    chain = [i for i in instruments if i["expiry"] == expiry]
    cmp_ = kite.ltp([INDEX_KEY])[INDEX_KEY]["last_price"]
    lot_size = chain[0]["lot_size"]
    qty = lot_size * LOTS
    strikes = {t: sorted(set(i["strike"] for i in chain if i["instrument_type"] == t)) for t in ("CE", "PE")}
    symbol = {(i["strike"], i["instrument_type"]): i["tradingsymbol"] for i in chain}

    legs = [  # protective wings FIRST, so the position is never naked mid-entry
        core.Leg("buy_ce", "CE", core.nearest_strike(strikes["CE"], cmp_ + LONG_OFFSET), "", True),
        core.Leg("buy_pe", "PE", core.nearest_strike(strikes["PE"], cmp_ - LONG_OFFSET), "", True),
        core.Leg("sell_ce", "CE", core.nearest_strike(strikes["CE"], cmp_ + SHORT_OFFSET), "", False),
        core.Leg("sell_pe", "PE", core.nearest_strike(strikes["PE"], cmp_ - SHORT_OFFSET), "", False),
    ]
    for leg in legs:
        leg.tradingsymbol = symbol[(leg.strike, leg.opt_type)]
        _, leg.entry_price = core.place_and_wait(kite, leg.tradingsymbol, leg.is_buy, qty, dry_run)

    net_credit = sum(l.entry_price * (-1 if l.is_buy else 1) for l in legs)
    state = core.CondorState(
        status="open", entry_date=today.isoformat(), expiry=expiry.isoformat(),
        lot_size=lot_size, qty=qty, net_credit=net_credit, legs=[asdict(l) for l in legs],
    )
    core.save_state(state, state_path)
    logger.info("ENTERED BankNifty condor: spot=%.2f expiry=%s strikes=%s credit/share=%.2f (Rs %.0f) qty=%d%s",
                cmp_, expiry, {l.name: l.strike for l in legs}, net_credit, net_credit * qty, qty,
                " [DRY RUN]" if dry_run else "")
    return state


def monitor_and_manage(kite, state: core.CondorState, dry_run: bool, until: time | None = None,
                       poll_seconds: float = 60.0) -> None:
    state_path, history_path = paths(dry_run)
    is_expiry_day = core.now_ist().date() >= date.fromisoformat(state.expiry)
    end = until or (EXPIRY_EXIT_TIME if is_expiry_day else MONITOR_END)
    threshold = core.stop_threshold(state, None, STOP_LOSS_RUPEES)
    logger.info("Monitoring position (expiry %s) until %s IST, stop at MTM <= Rs %.0f",
                state.expiry, end.strftime("%H:%M"), threshold)
    reason, mtm = core.monitor_until(kite, state, threshold, end, intraday_log(dry_run), poll_seconds)
    if reason == "stop":
        core.exit_position(kite, state, "stop_loss", dry_run, state_path, history_path)
    elif is_expiry_day and until is None:
        core.exit_position(kite, state, "expiry", dry_run, state_path, history_path)
    else:
        logger.info("Session monitoring done, holding. Last MTM: %s", "n/a" if mtm is None else f"Rs {mtm:.0f}")


def wait_until(t: time) -> None:
    while core.now_ist().time() < t:
        remaining = (datetime.combine(core.now_ist().date(), t, core.IST) - core.now_ist()).total_seconds()
        time_module.sleep(min(max(remaining, 1.0), 60.0))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Log intended orders without placing them.")
    ap.add_argument("--action", choices=["auto", "status", "enter", "monitor", "exit"], default="auto")
    ap.add_argument("--until", default=None, help="HH:MM IST, for --action monitor")
    ap.add_argument("--poll-seconds", type=float, default=60.0)
    args = ap.parse_args()

    cfg = load_config()
    cfg.logging.log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout),
                  logging.FileHandler(cfg.logging.log_dir / f"banknifty_condor_{core.now_ist().date()}.log")],
    )
    kite = get_kite_client(cfg)
    state_path, history_path = paths(args.dry_run)
    state = core.load_state(state_path)
    until = core.parse_hhmm(args.until) if args.until else None

    if args.action == "status":
        entry, expiry = is_entry_day(kite, core.now_ist().date(), args.dry_run)
        logger.info("Next expiry %s (%d days); entry day today: %s", expiry, (expiry - core.now_ist().date()).days, entry)
        if state:
            logger.info("Open position: %s  MTM now Rs %.0f", state.legs, core.position_mtm(kite, state))
        return
    if args.action == "enter":
        enter_position(kite, args.dry_run)
        return
    if args.action == "monitor":
        if state is None:
            logger.info("No open position to monitor.")
            return
        monitor_and_manage(kite, state, args.dry_run, until=until, poll_seconds=args.poll_seconds)
        return
    if args.action == "exit":
        if state is None:
            logger.info("No open position to exit.")
            return
        core.exit_position(kite, state, "manual", args.dry_run, state_path, history_path)
        return

    # auto: one process per trading day
    if state is not None:
        monitor_and_manage(kite, state, args.dry_run, poll_seconds=args.poll_seconds)
        return
    entry, expiry = is_entry_day(kite, core.now_ist().date(), args.dry_run)
    if not entry:
        logger.info("No open position and not an entry day (next expiry %s, %d days) -- nothing to do.",
                    expiry, (expiry - core.now_ist().date()).days)
        return
    logger.info("Entry day for the %s expiry -- entering at %s IST.", expiry, ENTRY_TIME.strftime("%H:%M"))
    wait_until(ENTRY_TIME)
    state = enter_position(kite, args.dry_run)
    if state is not None:
        monitor_and_manage(kite, state, args.dry_run, poll_seconds=args.poll_seconds)


if __name__ == "__main__":
    main()
