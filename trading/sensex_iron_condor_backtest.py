"""Backtest the weekly Iron Condor strategy on SENSEX, using real BSE options
settlement prices, adapted from the validated NIFTY version
(nifty_iron_condor_backtest.py -- see that file for the shared engine).

Two things do NOT carry over unchanged from the NIFTY analysis, and both were
verified empirically before being applied here:

1. Wing offsets must be scaled by price level, not copied as literal points.
   Nifty trades around 24,500; Sensex around 79,700 -- a ~3.26x ratio. A
   literal "200 pts / 400 pts" wing on Sensex is only ~0.25%/0.5% OTM (vs
   ~0.8%/1.6% on Nifty), i.e. far closer to the money, and backtests flat-out
   unprofitable (all 5 entry weekdays net negative, ~25-33% win rate).
   Scaling by the same price ratio gives ~700/1400 points, which reproduces
   NIFTY-like win rates (~60-70%) and profitability. Wing width must be
   chosen relative to the index's own level, not assumed portable.

2. Sensex's own weekly options have changed expiry weekday multiple times
   within this same 2-year window (Friday, then Tuesday, then Thursday, with
   holiday-shift noise on top) -- unlike Nifty's consistently Tuesday expiry.
   The shared engine already picks "nearest future expiry actually present
   in the data" rather than hardcoding a weekday, so this is handled
   automatically; entry weekday was re-swept from scratch rather than
   assuming Friday carries over (it happens to still win, but not by
   assumption).

Also fixed here (in the shared engine): a genuine BSE bhavcopy defect where
every SENSEX expiry-day row has ClsPric overwritten with the underlying spot
price (100% of expiry rows affected; verified 0% on NIFTY and 0% on any
non-expiry day). Exit-at-expiry now prices from settlement-price intrinsic
value instead of trusting ClsPric, which is also the more correct way to
price cash-settled index options at expiry in general.

Usage:
    python sensex_iron_condor_backtest.py
"""
from __future__ import annotations

import pandas as pd

from nifty_iron_condor_backtest import run_iron_condor

DATA_PATH = "data_cache/SENSEX_OPTIONS_bhavcopy.csv"
SHORT_OFFSET = 700
LONG_OFFSET = 1400
ENTRY_WEEKDAY = 4  # Friday, re-validated for Sensex (see module docstring)
LOTS = 5


def max_drawdown(results: pd.DataFrame, lots: int) -> float:
    pnl = results.sort_values("entry_date")["net_pnl"].values * lots
    cum = pnl.cumsum()
    peak = pd.Series(cum).cummax()
    return (cum - peak).min()


def main():
    df = pd.read_csv(DATA_PATH, parse_dates=["TradDt", "XpryDt"])
    end = df["TradDt"].max()
    windows = {
        "6-month": end - pd.Timedelta(days=182),
        "1-year": end - pd.Timedelta(days=365),
        "2-year": df["TradDt"].min(),
    }

    for label, start in windows.items():
        sub = df[df["TradDt"] >= start]
        print(f"=== {label} window ({start.date()} to {end.date()}) ===")
        for sl_label, sl in [("no stop", None), ("1.0x stop", 1.0), ("0.5x stop", 0.5)]:
            res = run_iron_condor(
                sub, short_offset=SHORT_OFFSET, long_offset=LONG_OFFSET,
                stop_loss_credit_multiple=sl, entry_weekday=ENTRY_WEEKDAY,
            )
            if res.empty:
                print(f"  {sl_label}: no trades")
                continue
            net = res["net_pnl"].sum() * LOTS
            wr = (res["net_pnl"] > 0).mean() * 100
            dd = max_drawdown(res, LOTS)
            print(
                f"  {sl_label}: n={len(res)}, net(5 lots)=Rs {net:,.0f}, "
                f"win_rate={wr:.1f}%, max_drawdown(5 lots)=Rs {dd:,.0f}"
            )
        print()


if __name__ == "__main__":
    main()
