"""Compare downside-protection rules for the Nifty weekly Iron Condor
(Friday entry, 5 lots) against the current config (200/400 symmetric, 1.0x
mid-week stop):

  (b) exit the put spread at the first daily close below the short PE
  (c) wider put wings from entry (call side stays 200/400)

Each variant runs on both entry versions: Friday close, and the prior-day
(usually Thursday) close as a conservative proxy for a 9:30am Friday entry.

Usage:
    python downside_protection_backtest.py
"""
from __future__ import annotations

import pandas as pd

from nifty_iron_condor_backtest import run_iron_condor

DATA_PATH = "data_cache/NIFTY_OPTIONS_bhavcopy.csv"
LOTS = 5

VARIANTS = [
    ("Current: 200/400, 1.0x stop", dict(stop_loss_credit_multiple=1.0)),
    ("(b) PE-breach exit + 1.0x stop", dict(stop_loss_credit_multiple=1.0, breach_exit_sides=("PE",))),
    ("(b) PE-breach exit, no stop", dict(breach_exit_sides=("PE",))),
    ("(c) puts 250/450, 1.0x stop", dict(stop_loss_credit_multiple=1.0, put_short_offset=250, put_long_offset=450)),
    ("(c) puts 300/500, 1.0x stop", dict(stop_loss_credit_multiple=1.0, put_short_offset=300, put_long_offset=500)),
    ("(c) puts 400/600, 1.0x stop", dict(stop_loss_credit_multiple=1.0, put_short_offset=400, put_long_offset=600)),
    ("(b)+(c) puts 300/500 + breach", dict(stop_loss_credit_multiple=1.0, put_short_offset=300, put_long_offset=500, breach_exit_sides=("PE",))),
]


def max_drawdown(res: pd.DataFrame) -> float:
    pnl = res.sort_values("entry_date")["net_pnl"].values * LOTS
    cum = pnl.cumsum()
    return (cum - pd.Series(cum).cummax()).min()


def summarize(res: pd.DataFrame, start: pd.Timestamp) -> str:
    r = res[res["entry_date"] >= start]
    return (
        f"Rs {r['net_pnl'].sum() * LOTS:>9,.0f}  wr {(r['net_pnl'] > 0).mean() * 100:4.1f}%  "
        f"dd {max_drawdown(r):>9,.0f}  worst {r['net_pnl'].min() * LOTS:>8,.0f}"
    )


def main():
    df = pd.read_csv(DATA_PATH, parse_dates=["TradDt", "XpryDt"])
    end = df["TradDt"].max()
    windows = {"6m": end - pd.Timedelta(days=182), "1y": end - pd.Timedelta(days=365), "2y": df["TradDt"].min()}

    for entry_label, prior in [("FRIDAY CLOSE ENTRY", False), ("THURSDAY-CLOSE PROXY (conservative 9:30am stand-in)", True)]:
        print(f"\n=== {entry_label} ===")
        for label, kw in VARIANTS:
            res = run_iron_condor(df, 200, 400, entry_weekday=4, enter_prior_close=prior, **kw)
            breaches = res["exit_reason"].str.contains("breach").sum()
            stops = (res["exit_reason"] == "stop_loss").sum()
            print(f"\n{label}   [n={len(res)}, put breaches={breaches}, stops={stops}]")
            for w, start in windows.items():
                print(f"   {w}: {summarize(res, start)}")


if __name__ == "__main__":
    main()
