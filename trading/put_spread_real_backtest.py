"""Replay the intraday Nifty bear put debit spread on REAL minute option prices
from Kite (read-only -- places no orders). Run on the VPS after the morning
login:
    venv/bin/python put_spread_real_backtest.py [--days 30] [--entry 09:30]

Same rules as nifty_put_spread_intraday.py: at the entry minute buy the ATM PE
and sell the PE 200 points lower, 5 lots; exit on a loss of 40% of the debit,
Nifty 200 points below entry, the spread worth 2x the debit, or 15:10.

Limitation: Kite serves history only for contracts that have NOT expired. For
a past day the strategy would have used that week's (now expired) contract,
so the replay uses the nearest expiry that is still listed and had data that
day; the 'dte' column shows how many days to expiry it actually had. More
days to expiry means a cheaper-to-move, slower spread than the live trade
would have had on that day -- compare rows by dte. Prices are minute-candle
opens/closes, not bid/ask: SLIP rupees per share per leg per side is added.
Minute data is cached under data_cache/kite_minute/ so reruns are fast.
"""
from __future__ import annotations

import argparse
import time as time_module
from datetime import date, datetime, timedelta

import pandas as pd

from config import BASE_DIR, load_config
from data import get_kite_client
from nifty_iron_condor_backtest import leg_charges

LOTS = 5
WIDTH, STOP_PCT, PROFIT_MULT, TARGET_PTS = 200, 0.40, 2.0, 200
EXIT_HHMM = "15:10"
SLIP = 0.5
CACHE = BASE_DIR / "data_cache" / "kite_minute"


def minute_bars(kite, token: int, day: date) -> pd.DataFrame:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{token}_{day}.csv"
    if path.exists():
        df = pd.read_csv(path)
    else:
        time_module.sleep(0.35)  # Kite historical API: max 3 requests/second
        rows = kite.historical_data(token, datetime.combine(day, datetime.min.time()).replace(hour=9, minute=15),
                                    datetime.combine(day, datetime.min.time()).replace(hour=15, minute=30), "minute")
        df = pd.DataFrame(rows)
        if len(df):
            df["hhmm"] = pd.to_datetime(df["date"]).dt.strftime("%H:%M")
        if day < date.today():  # today's bars are still growing -- don't cache
            df.to_csv(path, index=False)
    return df


def run(kite, days: int, entry: str) -> pd.DataFrame:
    nifty_token = next(i["instrument_token"] for i in kite.instruments("NSE") if i["tradingsymbol"] == "NIFTY 50")
    puts = [i for i in kite.instruments("NFO") if i["name"] == "NIFTY" and i["segment"] == "NFO-OPT"
            and i["instrument_type"] == "PE"]
    by_expiry: dict[date, dict[float, dict]] = {}
    for i in puts:
        by_expiry.setdefault(i["expiry"], {})[i["strike"]] = i
    expiries = sorted(by_expiry)
    lot = puts[0]["lot_size"]
    qty = lot * LOTS

    out = []
    for back in range(days * 2 + 15):  # calendar days, newest first
        if len(out) >= days:
            break
        day = date.today() - timedelta(days=back)
        if day.weekday() >= 5:
            continue
        idx = minute_bars(kite, nifty_token, day)
        if idx.empty or entry not in set(idx.hhmm):
            continue
        idx = idx.set_index("hhmm")
        s0 = float(idx.loc[entry, "open"])
        trade = None
        for exp in (e for e in expiries if e >= day):
            strikes = sorted(by_expiry[exp])
            atm = min(strikes, key=lambda k: abs(k - s0))
            low = min(strikes, key=lambda k: abs(k - (atm - WIDTH)))
            a = minute_bars(kite, by_expiry[exp][atm]["instrument_token"], day)
            b = minute_bars(kite, by_expiry[exp][low]["instrument_token"], day)
            if a.empty or b.empty or entry not in set(a.hhmm) or entry not in set(b.hhmm):
                continue  # contract not trading that day (listed later) -- try the next expiry
            trade = (exp, atm, low, a.set_index("hhmm"), b.set_index("hhmm"))
            break
        if trade is None:
            print(f"{day}: no listed contract with data -- skipped")
            continue
        exp, atm, low, a, b = trade
        buy_in, sell_in = float(a.loc[entry, "open"]) + SLIP, float(b.loc[entry, "open"]) - SLIP
        debit = buy_in - sell_in
        reason, exit_val, exit_at = "time", None, None
        for hhmm in a.index:
            if hhmm < entry or hhmm not in b.index or hhmm not in idx.index:
                continue
            v = float(a.loc[hhmm, "close"]) - float(b.loc[hhmm, "close"])
            if float(idx.loc[hhmm, "low"]) <= s0 - TARGET_PTS:
                reason = "target_points"
            elif v - debit <= -STOP_PCT * debit:
                reason = "stop_loss"
            elif v >= PROFIT_MULT * debit:
                reason = "target_double"
            elif hhmm >= EXIT_HHMM:
                reason = "time"
            else:
                continue
            buy_out, sell_out = float(a.loc[hhmm, "close"]) - SLIP, float(b.loc[hhmm, "close"]) + SLIP
            exit_val, exit_at = buy_out - sell_out, hhmm
            break
        if exit_val is None:
            continue
        gross = (exit_val - debit) * qty
        charges = (leg_charges(buy_in, qty, True) + leg_charges(sell_in, qty, False)
                   + leg_charges(buy_out, qty, False) + leg_charges(sell_out, qty, True))
        out.append(dict(day=day, weekday=day.strftime("%a"), expiry=exp, dte=(exp - day).days, spot=round(s0, 1),
                        buy=atm, sell=low, debit=round(debit, 2), exit=round(exit_val, 2), exit_at=exit_at,
                        reason=reason, pnl=round(gross - charges)))
        print(f"{day} {day:%a} exp {exp} ({(exp - day).days}d)  {atm:.0f}/{low:.0f}  debit {debit:6.2f}  "
              f"exit {exit_val:6.2f} @ {exit_at} {reason:<13} P&L Rs {gross - charges:>8,.0f}")
    return pd.DataFrame(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30, help="how many recent trading days to replay")
    ap.add_argument("--entry", default="09:30")
    args = ap.parse_args()
    kite = get_kite_client(load_config())
    r = run(kite, args.days, args.entry)
    if r.empty:
        print("No trades replayed.")
        return
    r = r.sort_values("day")
    (BASE_DIR / "logs").mkdir(exist_ok=True)
    r.to_csv(BASE_DIR / "logs" / "put_spread_real_backtest.csv", index=False)
    w = r.pnl > 0
    print(f"\n{len(r)} days, entry {args.entry}, {LOTS} lots: total Rs {r.pnl.sum():,.0f}, avg {r.pnl.mean():,.0f}, "
          f"win rate {w.mean():.0%}, best {r.pnl.max():,.0f}, worst {r.pnl.min():,.0f}")
    print("by days to expiry actually used:")
    print(r.groupby("dte").pnl.agg(["count", "sum", "mean"]).round(0).to_string())
    print("by weekday:")
    print(r.groupby("weekday").pnl.agg(["count", "sum", "mean"]).round(0).to_string())
    print("exit reasons:", r.reason.value_counts().to_dict())
    print("saved logs/put_spread_real_backtest.csv")


if __name__ == "__main__":
    main()
