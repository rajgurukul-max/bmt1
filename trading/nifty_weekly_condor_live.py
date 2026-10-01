"""Live weekly Nifty Iron Condor -- PLACES REAL ORDERS unless --dry-run.

Configuration (nifty_iron_condor_backtest.py, 2 years of real NSE settlement
data; Rs 5.29L net on 5 lots with a Friday-close entry and 1.0x stop):
  - Enter Friday at ENTRY_TIME (near the close, matching the backtest):
    sell CE/PE 200 pts OTM, buy CE/PE 400 pts OTM, 5 lots, product NRML.
  - Exit the whole position when its loss reaches the TIGHTER of 1.0x the net
    credit collected or Rs 25,000, checked EVERY MINUTE through the trading
    day, expiry day included. (A once-a-day close check missed every large
    loss in the backtest: they happened on expiry day, or gapped past the
    line overnight.)
  - Otherwise hold to the following weekly expiry and close at
    EXPIRY_EXIT_TIME on expiry day.

Run ONE long-lived process per trading day, started before the open:
    10 9 * * 1-5  cd /path/to/trading && venv/bin/python nifty_weekly_condor_live.py >> logs/nifty_condor_cron.log 2>&1
It monitors any open position until 15:25 (exits at 15:15 on expiry day), and
on Fridays with no position it enters at ENTRY_TIME and monitors the rest of
the session.

Manual actions (for testing / intervention):
    --action status | enter | check | monitor | exit   (add --dry-run to place nothing)
    --until HH:MM  --poll-seconds N                   (monitor tuning)
    (check = one immediate stop test, the old once-a-day behaviour)

Safety: refuses a second position while one is open; dry runs use separate
state/history files; `touch KILL_SWITCH` blocks new entries (an open position
keeps being monitored and stopped out as normal).
"""
from __future__ import annotations

import argparse
import logging
import sys
import time as time_module
from datetime import date, datetime, time

import condor_live_core as core
from config import BASE_DIR, load_config
from data import get_kite_client

logger = logging.getLogger("nifty_weekly_condor")

STATE_FILE = BASE_DIR / "nifty_condor_state.json"
HISTORY_FILE = BASE_DIR / "logs" / "nifty_condor_history.csv"
KILL_SWITCH_FILE = BASE_DIR / "KILL_SWITCH"

SHORT_OFFSET = 200
LONG_OFFSET = 400
LOTS = 5
STOP_LOSS_CREDIT_MULTIPLE = 1.0
STOP_LOSS_RUPEES = 25000
ENTRY_WEEKDAY = 4                # Friday (0=Monday .. 4=Friday)
ENTRY_TIME = time(15, 15)        # backtest entered at Friday's close
MONITOR_END = time(15, 25)
EXPIRY_EXIT_TIME = time(15, 15)
INDEX_KEY = "NSE:NIFTY 50"
FNO_NAME = "NIFTY"


def today() -> date:
    return core.now_ist().date()


def paths(dry_run: bool):
    return core.dry_path(STATE_FILE, dry_run), core.dry_path(HISTORY_FILE, dry_run)


def intraday_log(dry_run: bool):
    return core.dry_path(BASE_DIR / "logs" / f"nifty_condor_intraday_{today()}.csv", dry_run)


def week_chain(kite, after: date) -> tuple[list[dict], date]:
    opts = [i for i in kite.instruments(core.EXCHANGE) if i["name"] == FNO_NAME and i["segment"] == "NFO-OPT"]
    expiry = min(i["expiry"] for i in opts if i["expiry"] > after)
    return [i for i in opts if i["expiry"] == expiry], expiry


def is_entry_day(d: date) -> bool:
    """Friday, or the last trading day before it when Friday is a holiday
    (e.g. Thursday 1 Oct 2026, with Friday 2 Oct Gandhi Jayanti). Backtest:
    Thursday-close entries into the next Tuesday expiry earned about the same
    as Friday-close ones (70% vs 77% win rate, ~Rs 6.5k vs ~7.2k per trade)."""
    return core.is_last_trading_day_through(d, ENTRY_WEEKDAY, core.load_holidays())


def enter_position(kite, dry_run: bool) -> core.CondorState | None:
    state_path, history_path = paths(dry_run)
    if core.load_state(state_path) is not None:
        raise RuntimeError("A position is already open -- refusing to enter another one.")
    if KILL_SWITCH_FILE.exists():
        logger.warning("KILL_SWITCH present -- skipping entry.")
        return None

    chain, expiry = week_chain(kite, today())
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
    state = core.enter_condor(kite, legs, qty, lot_size, expiry, dry_run, state_path, history_path, "Nifty")
    logger.info("ENTERED Nifty condor: spot=%.2f expiry=%s strikes=%s credit/share=%.2f (Rs %.0f) qty=%d stop Rs %.0f%s",
                cmp_, expiry, {l.name: l.strike for l in legs}, state.net_credit, state.net_credit * qty, qty,
                threshold_for(state), " [DRY RUN]" if dry_run else "")
    return state


def threshold_for(state: core.CondorState) -> float:
    return core.stop_threshold(state, STOP_LOSS_CREDIT_MULTIPLE, STOP_LOSS_RUPEES)


def monitor_and_manage(kite, state: core.CondorState, dry_run: bool, until: time | None = None,
                       poll_seconds: float = 60.0) -> None:
    state_path, history_path = paths(dry_run)
    is_expiry_day = today() >= date.fromisoformat(state.expiry)
    end = until or (EXPIRY_EXIT_TIME if is_expiry_day else MONITOR_END)
    threshold = threshold_for(state)
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
        remaining = (datetime.combine(today(), t, core.IST) - core.now_ist()).total_seconds()
        time_module.sleep(min(max(remaining, 1.0), 60.0))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Log intended orders without placing them.")
    ap.add_argument("--action", choices=["auto", "status", "enter", "check", "monitor", "exit"], default="auto")
    ap.add_argument("--until", default=None, help="HH:MM IST, for --action monitor")
    ap.add_argument("--poll-seconds", type=float, default=60.0)
    ap.add_argument("--entry-time", default=None,
                    help=f"HH:MM IST entry time for auto mode (default {ENTRY_TIME.strftime('%%H:%%M')})")
    args = ap.parse_args()

    cfg = load_config()
    cfg.logging.log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout),
                  logging.FileHandler(cfg.logging.log_dir / f"nifty_condor_{today()}.log")],
    )
    if args.action == "auto" and not core.is_trading_day(today(), core.load_holidays()):
        logger.info("Exchange holiday -- nothing to do.")
        return
    kite = core.connect_when_token_valid() if args.action == "auto" else get_kite_client(cfg)
    state_path, history_path = paths(args.dry_run)
    state = core.load_state(state_path)
    until = core.parse_hhmm(args.until) if args.until else None

    if args.action == "status":
        if state is None:
            logger.info("No open position. Entry day today: %s", is_entry_day(today()))
        else:
            logger.info("Open position expiry %s, MTM now Rs %.0f, stop at Rs %.0f",
                        state.expiry, core.position_mtm(kite, state), threshold_for(state))
        return
    if args.action == "enter":
        enter_position(kite, args.dry_run)
        return
    if args.action in ("check", "monitor", "exit") and state is None:
        logger.info("No open position.")
        return
    if args.action == "check":
        mtm, threshold = core.position_mtm(kite, state), threshold_for(state)
        logger.info("Check: MTM Rs %.0f, stop at Rs %.0f", mtm, threshold)
        if mtm <= threshold:
            core.exit_position(kite, state, "stop_loss", args.dry_run, state_path, history_path)
        return
    if args.action == "monitor":
        monitor_and_manage(kite, state, args.dry_run, until=until, poll_seconds=args.poll_seconds)
        return
    if args.action == "exit":
        core.exit_position(kite, state, "manual", args.dry_run, state_path, history_path)
        return

    # auto: one process per trading day
    if state is not None:
        monitor_and_manage(kite, state, args.dry_run, poll_seconds=args.poll_seconds)
        return
    if not is_entry_day(today()):
        logger.info("No open position and today is not the entry day -- nothing to do.")
        return
    entry_time = core.parse_hhmm(args.entry_time) if args.entry_time else ENTRY_TIME
    logger.info("Entry day -- entering at %s IST.", entry_time.strftime("%H:%M"))
    wait_until(entry_time)
    state = enter_position(kite, args.dry_run)
    if state is not None:
        monitor_and_manage(kite, state, args.dry_run, poll_seconds=args.poll_seconds)


if __name__ == "__main__":
    main()
