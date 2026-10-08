"""Intraday Nifty bear put debit spread. PAPER TRADES BY DEFAULT -- real orders
only with --live.

Not backtested (no intraday option history): run it in paper mode first. In
the backtest data a weak morning or a big down day did NOT on average lead to
further intraday falls, so this is a discretionary trade -- you decide when.

When you run it:
  - Buy LOTS x the ATM Nifty PE, then sell LOTS x the PE SPREAD_WIDTH points
    lower (nearest weekly expiry, NRML). The bought leg goes first so the sold
    leg is never naked; exits buy back the sold leg first.
  - Exit the first of:
      stop    -- loss reaches STOP_PCT of the debit paid (amount at risk)
      target  -- Nifty falls TARGET_POINTS from the entry spot, or the spread
                 is worth PROFIT_MULTIPLE x the debit (profit = amount at risk)
      time    -- EXIT_TIME
    checked every --poll-seconds.

Usage (on the VPS, after the morning login):
    venv/bin/python nifty_put_spread_intraday.py                  # PAPER: enter now, manage to exit
    venv/bin/python nifty_put_spread_intraday.py --live           # REAL ORDERS
    ... --action status | exit        (add --live for the real position)
Run it in the background so closing the SSH session doesn't stop it:
    nohup venv/bin/python nifty_put_spread_intraday.py >> logs/put_spread_cron.log 2>&1 &

Paper fills use the LTP +/- the same 2% buffer as real limit orders, so paper
results are slightly pessimistic. Paper and live use separate state/history
files (*.dryrun.*). Shares the account with the condor: both use margin, and
exits read the account's real positions, so overlapping strikes are safe.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time as time_module
from datetime import date, time

import condor_live_core as core
from config import BASE_DIR, load_config
from data import get_kite_client

logger = logging.getLogger("nifty_put_spread")

STATE_FILE = BASE_DIR / "put_spread_state.json"
HISTORY_FILE = BASE_DIR / "logs" / "put_spread_history.csv"

LOTS = 5
SPREAD_WIDTH = 200
STOP_PCT = 0.40            # exit when the loss reaches 40% of the debit
PROFIT_MULTIPLE = 2.0      # or when the spread is worth 2x the debit
TARGET_POINTS = 200        # or when Nifty is 200 points below the entry spot
EXIT_TIME = time(15, 10)
INDEX_KEY = "NSE:NIFTY 50"
FNO_NAME = "NIFTY"


def paths(paper: bool):
    return core.dry_path(STATE_FILE, paper), core.dry_path(HISTORY_FILE, paper)


def log_path(paper: bool):
    return core.dry_path(BASE_DIR / "logs" / f"put_spread_intraday_{core.now_ist().date()}.csv", paper)


def spot(kite) -> float:
    return kite.ltp([INDEX_KEY])[INDEX_KEY]["last_price"]


def enter(kite, paper: bool) -> core.CondorState:
    state_path, history_path = paths(paper)
    if core.load_state(state_path) is not None:
        raise RuntimeError("A put spread is already open -- refusing to enter another one.")
    now = core.now_ist().time()
    if not (core.MARKET_OPEN <= now < EXIT_TIME):
        raise RuntimeError(f"Outside the entry window ({core.MARKET_OPEN:%H:%M}-{EXIT_TIME:%H:%M}).")

    today = core.now_ist().date()
    puts = [i for i in kite.instruments(core.EXCHANGE)
            if i["name"] == FNO_NAME and i["segment"] == "NFO-OPT" and i["instrument_type"] == "PE"]
    expiry = min(i["expiry"] for i in puts if i["expiry"] >= today)
    chain = {i["strike"]: i for i in puts if i["expiry"] == expiry}
    strikes = sorted(chain)
    cmp_ = spot(kite)
    atm = core.nearest_strike(strikes, cmp_)
    low = core.nearest_strike(strikes, atm - SPREAD_WIDTH)
    lot_size = chain[atm]["lot_size"]
    qty = lot_size * LOTS
    legs = [  # bought leg FIRST, so the sold leg is never naked
        core.Leg("buy_pe", "PE", atm, chain[atm]["tradingsymbol"], True),
        core.Leg("sell_pe", "PE", low, chain[low]["tradingsymbol"], False),
    ]
    state = core.enter_condor(kite, legs, qty, lot_size, expiry, paper, state_path, history_path, "Put spread")
    debit = -state.net_credit
    # Remember the entry spot for the points target (CondorState has no field for it).
    state.legs[0]["entry_spot"] = cmp_
    core.save_state(state, state_path)
    logger.info("ENTERED put spread%s: spot %.2f, buy %s / sell %s (expiry %s), debit %.2f/share = Rs %.0f at risk; "
                "stop Rs %.0f, target Nifty <= %.0f or +Rs %.0f, time exit %s",
                " [PAPER]" if paper else "", cmp_, atm, low, expiry, debit, debit * qty,
                -STOP_PCT * debit * qty, cmp_ - TARGET_POINTS, (PROFIT_MULTIPLE - 1) * debit * qty,
                EXIT_TIME.strftime("%H:%M"))
    return state


def check(kite, state: core.CondorState) -> tuple[str | None, float, float]:
    """(exit_reason or None, mtm, spot) for one poll."""
    debit, qty = -state.net_credit, state.qty
    mtm, s = core.position_mtm(kite, state), spot(kite)
    if mtm <= -STOP_PCT * debit * qty:
        return "stop_loss", mtm, s
    if s <= state.legs[0]["entry_spot"] - TARGET_POINTS:
        return "target_points", mtm, s
    if mtm >= (PROFIT_MULTIPLE - 1) * debit * qty:
        return "target_double", mtm, s
    return None, mtm, s


def manage(kite, state: core.CondorState, paper: bool, poll_seconds: float) -> float:
    state_path, history_path = paths(paper)
    while True:
        if core.now_ist().time() >= EXIT_TIME:
            reason = "time"
            break
        try:
            reason, mtm, s = check(kite, state)
        except Exception as exc:  # broker hiccup: keep watching
            logger.warning("Poll failed (%s) -- retrying in %.0fs", exc, poll_seconds)
            time_module.sleep(poll_seconds)
            continue
        core.append_csv({"time_ist": core.now_ist().strftime("%Y-%m-%d %H:%M:%S"), "spot": s, "mtm": round(mtm, 2)},
                        log_path(paper))
        if reason:
            logger.warning("EXIT signal %s: MTM Rs %.0f, Nifty %.2f", reason, mtm, s)
            break
        time_module.sleep(poll_seconds)
    return core.exit_position(kite, state, reason, paper, state_path, history_path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="Place REAL orders (default: paper trade).")
    ap.add_argument("--action", choices=["run", "status", "exit"], default="run")
    ap.add_argument("--poll-seconds", type=float, default=15.0)
    args = ap.parse_args()
    paper = not args.live

    cfg = load_config()
    cfg.logging.log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout),
                  logging.FileHandler(cfg.logging.log_dir / f"put_spread_{core.now_ist().date()}.log")],
    )
    kite = get_kite_client(cfg)
    state_path, history_path = paths(paper)
    state = core.load_state(state_path)
    mode = "PAPER" if paper else "LIVE"

    if args.action == "status":
        if state is None:
            logger.info("[%s] No open put spread.", mode)
        else:
            reason, mtm, s = check(kite, state)
            logger.info("[%s] Open put spread %s, MTM Rs %.0f, Nifty %.2f (entry %.2f)%s", mode,
                        [(l["name"], l["strike"]) for l in state.legs], mtm, s, state.legs[0]["entry_spot"],
                        f" -- exit condition met: {reason}" if reason else "")
        return
    if args.action == "exit":
        if state is None:
            logger.info("[%s] No open put spread.", mode)
            return
        core.exit_position(kite, state, "manual", paper, state_path, history_path)
        return

    # run: enter now (or resume a position opened earlier today), manage to exit
    if state is not None and date.fromisoformat(state.entry_date) != core.now_ist().date():
        raise RuntimeError("An open put spread from an earlier day exists -- check it and use --action exit.")
    if state is None:
        logger.warning("[%s] Entering the put spread now.", mode)
        state = enter(kite, paper)
    else:
        logger.info("[%s] Resuming the open put spread.", mode)
    manage(kite, state, paper, args.poll_seconds)


if __name__ == "__main__":
    main()
