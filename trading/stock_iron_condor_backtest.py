"""Test whether the Nifty/Sensex weekly Iron Condor structure transfers to a
single NSE stock (e.g. RELIANCE) at its native MONTHLY expiry cadence, using
real settlement data from data_cache/{SYMBOL}_OPTIONS_bhavcopy.csv
(download_stock_options.py).

Two structural adjustments from the index version, both necessary and applied
here (see nifty_iron_condor_backtest.run_iron_condor docstrings for the
underlying mechanics):

1. pct_offsets=True: wing width is set as %OTM of that day's CMP rather than
   literal points, since a single stock's price level isn't stable the way an
   index's roughly is -- RELIANCE alone moved from ~2,900 to ~1,250 mid-window
   on a 1:1 bonus issue. Nifty's validated 200/400-point wings are ~0.82%/1.64%
   OTM; that percentage is what's reused here, not the point values.

2. days_to_expiry (not entry_weekday): stocks have exactly one expiry a month,
   so a weekday-based entry rule would fire multiple overlapping trades against
   the same expiry within one cycle. days_to_expiry picks at most one trading
   day per expiry cycle, which is what "once a month" actually requires.

Usage:
    python stock_iron_condor_backtest.py RELIANCE                  # default: Nifty's 200/400 pts, scaled to %OTM
    python stock_iron_condor_backtest.py ITC --short 20 --long 40 --points  # literal points, not %OTM
"""
from __future__ import annotations

import argparse

import pandas as pd

from nifty_iron_condor_backtest import run_iron_condor

DEFAULT_SHORT_PCT = 200 / 24450 * 100  # Nifty's validated 200-pt short wing, as %OTM
DEFAULT_LONG_PCT = 400 / 24450 * 100   # Nifty's validated 400-pt long wing, as %OTM


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol")
    ap.add_argument("--short", type=float, default=None, help="short wing (percent OTM by default, or literal points with --points)")
    ap.add_argument("--long", type=float, default=None, help="long wing (percent OTM by default, or literal points with --points)")
    ap.add_argument("--points", action="store_true", help="treat --short/--long as literal index points instead of percent OTM")
    args = ap.parse_args()
    symbol = args.symbol.upper()
    pct_offsets = not args.points
    short_off = args.short if args.short is not None else (DEFAULT_SHORT_PCT if pct_offsets else 200)
    long_off = args.long if args.long is not None else (DEFAULT_LONG_PCT if pct_offsets else 400)

    df = pd.read_csv(f"data_cache/{symbol}_OPTIONS_bhavcopy.csv", parse_dates=["TradDt", "XpryDt"])
    print(f"{symbol}: {df['TradDt'].nunique()} trading days, {df['XpryDt'].nunique()} monthly expiries")
    unit = "% OTM" if pct_offsets else "points"
    print(f"Wings: short={short_off:.3f}{unit}, long={long_off:.3f}{unit}\n")

    for dte in [3, 4, 5, 6, 7, 10, 14, 21, 28]:
        res = run_iron_condor(
            df, short_offset=short_off, long_offset=long_off,
            stop_loss_credit_multiple=None, days_to_expiry=dte, pct_offsets=pct_offsets,
        )
        if res.empty:
            print(f"{dte:>2}d before expiry: no trades")
            continue
        wr = (res["net_pnl"] > 0).mean() * 100
        print(
            f"{dte:>2}d before expiry: n={len(res):>2}, net(1 lot)=Rs {res['net_pnl'].sum():>9,.0f}, "
            f"avg=Rs {res['net_pnl'].mean():>7,.0f}, win_rate={wr:>5.1f}%, worst=Rs {res['net_pnl'].min():>8,.0f}"
        )


if __name__ == "__main__":
    main()
