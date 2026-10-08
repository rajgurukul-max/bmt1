"""Model backtest of the intraday Nifty bear put debit spread
(nifty_put_spread_intraday.py): buy the ATM PE, sell the PE 200 points lower,
5 lots, nearest weekly (Tuesday) expiry; exit on a 40%-of-debit loss, Nifty
200 points below entry, spread worth 2x the debit, or 15:10.

There is no historical intraday OPTION data here, so option prices are
modelled (Black-Scholes) from the real 5-minute Nifty path, the previous
day's India VIX as implied volatility (+1.5 vol points for the lower, more
skewed strike), and the real time left to expiry. Costs: Rs 0.75 per share
per leg per side for bid/ask, plus the project's Zerodha charge model.
Treat the rupee results as estimates, not fills.

Usage:
    python put_spread_model_backtest.py [--entry 09:30]
"""
from __future__ import annotations

import argparse
import math
from datetime import datetime, timedelta

import pandas as pd

from nifty_iron_condor_backtest import leg_charges

SPOT_FILE = "data_cache/NIFTY 50_NSE_5minute.csv"
VIX_FILE = "data_cache/INDIA_VIX_daily.csv"
LOTS, LOT = 5, 65
WIDTH, STOP_PCT, PROFIT_MULT, TARGET_PTS = 200, 0.40, 2.0, 200
SKEW = 0.015
SLIP = 0.75
EXPIRY_WEEKDAY = 1  # Tuesday


def ncdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def put(s: float, k: float, t: float, vol: float) -> float:
    if t <= 0:
        return max(k - s, 0.0)
    d1 = (math.log(s / k) + 0.5 * vol * vol * t) / (vol * math.sqrt(t))
    d2 = d1 - vol * math.sqrt(t)
    return k * ncdf(-d2) - s * ncdf(-d1)


def spread_value(s, atm, low, t, vix):
    return put(s, atm, t, vix) - put(s, low, t, vix + SKEW)


def years_to_expiry(ts: datetime) -> float:
    exp_day = ts.date() + timedelta(days=(EXPIRY_WEEKDAY - ts.weekday()) % 7)
    expiry = datetime.combine(exp_day, datetime.strptime("15:30", "%H:%M").time(), ts.tzinfo)
    return max((expiry - ts).total_seconds(), 0) / (365 * 86400)


def simulate(entry_hhmm: str) -> pd.DataFrame:
    m = pd.read_csv(SPOT_FILE)
    m["ts"] = pd.to_datetime(m["date"])
    m["day"] = m.ts.dt.date
    vix = pd.read_csv(VIX_FILE)
    vix["day"] = pd.to_datetime(vix["date"]).dt.date
    vix = vix.set_index("day")["close"] / 100
    qty = LOTS * LOT
    prev_close, rows = None, []
    for day, g in m.groupby("day"):
        g = g.reset_index(drop=True)
        hhmm = g.ts.dt.strftime("%H:%M")
        prior_vix = vix[vix.index < day]
        if prev_close is None or prior_vix.empty or entry_hhmm not in set(hhmm):
            prev_close = g.close.iloc[-1]
            continue
        iv = float(prior_vix.iloc[-1])
        i0 = int((hhmm == entry_hhmm).idxmax())
        s0, t0 = g.open[i0], years_to_expiry(g.ts[i0].to_pydatetime())
        atm = round(s0 / 50) * 50
        low = atm - WIDTH
        debit = spread_value(s0, atm, low, t0, iv) + 2 * SLIP
        reason, exit_val = "time", None
        for i in range(i0, len(g)):
            ts = g.ts[i].to_pydatetime()
            t = years_to_expiry(ts)
            if g.low[i] <= s0 - TARGET_PTS:
                exit_val, reason = spread_value(s0 - TARGET_PTS, atm, low, t, iv), "target_points"
                break
            v = spread_value(g.close[i], atm, low, t, iv)
            if v - debit <= -STOP_PCT * debit:
                exit_val, reason = v, "stop_loss"
                break
            if v >= PROFIT_MULT * debit:
                exit_val, reason = v, "target_double"
                break
            if hhmm[i] >= "15:10":
                exit_val = v
                break
        exit_val -= 2 * SLIP
        gross = (exit_val - debit) * qty
        charges = sum(leg_charges(p, qty, b) for p, b in ((debit / 2, True), (debit / 2, False), (exit_val / 2, True), (exit_val / 2, False)))
        rows.append(dict(day=day, weekday=day.strftime("%a"), dte=round(t0 * 365, 1), vix=round(iv * 100, 1),
                         gap=g.open[0] / prev_close - 1, open_to_entry=s0 / g.open[0] - 1,
                         prev_day=None, spot=s0, debit=round(debit, 1), exit=round(exit_val, 1),
                         reason=reason, pnl=round(gross - charges)))
        prev_close = g.close.iloc[-1]
    out = pd.DataFrame(rows)
    closes = m.groupby("day").close.last()
    out["prev_day"] = out.day.map(closes.pct_change().shift(1))  # the day BEFORE (known at entry)
    return out


def show(r: pd.DataFrame, label: str) -> None:
    if not len(r):
        return
    w = r.pnl > 0
    print(f"{label:<40} n={len(r):>3}  total Rs {r.pnl.sum():>9,.0f}  avg {r.pnl.mean():>7,.0f}  win {w.mean():>4.0%}  "
          f"avg win {r.pnl[w].mean() if w.any() else 0:>7,.0f}  avg loss {r.pnl[~w].mean() if (~w).any() else 0:>8,.0f}  "
          f"best {r.pnl.max():>7,.0f}  worst {r.pnl.min():>8,.0f}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--entry", default="09:30")
    args = ap.parse_args()
    r = simulate(args.entry)
    print(f"Model backtest, entry {args.entry}, {r.day.min()} .. {r.day.max()}, 5 lots\n")
    show(r, "every trading day")
    for wd in ("Wed", "Thu", "Fri", "Mon", "Tue"):
        show(r[r.weekday == wd], f"  {wd} (avg {r[r.weekday == wd].dte.mean():.1f} days to expiry)")
    show(r[r.prev_day <= -0.01], "previous day fell 1%+")
    show(r[r.gap <= -0.003], "gap-down open (0.3%+)")
    show(r[r.open_to_entry <= -0.002], "falling 9:15->entry (0.2%+)")
    show(r[(r.prev_day <= -0.01) | (r.gap <= -0.003)], "prev day -1% OR gap-down")
    print("\nexit reasons:", r.reason.value_counts().to_dict())
    print(f"avg debit Rs {r.debit.mean():.0f}/share = Rs {r.debit.mean() * LOTS * LOT:,.0f} at risk")
    print("\nlast 20 trading days:")
    print(r.tail(20)[["day", "weekday", "dte", "vix", "spot", "debit", "exit", "reason", "pnl"]].to_string(index=False))


if __name__ == "__main__":
    main()
