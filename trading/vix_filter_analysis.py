"""Test whether filtering the already-validated Nifty weekly Iron Condor
(200/400 wings, Friday entry, 1.0x mid-week stop) by that day's India VIX
level improves results, following widely-cited retail-trader guidance to
avoid selling premium when VIX is elevated (see conversation/commit history
for sources). Uses real settlement data + real VIX history, not anecdote.

Usage:
    python vix_filter_analysis.py
"""
from __future__ import annotations

import pandas as pd

from nifty_iron_condor_backtest import run_iron_condor

OPTIONS_PATH = "data_cache/NIFTY_OPTIONS_bhavcopy.csv"
VIX_PATH = "data_cache/INDIA_VIX_daily.csv"


def main():
    df = pd.read_csv(OPTIONS_PATH, parse_dates=["TradDt", "XpryDt"])
    res = run_iron_condor(df, short_offset=200, long_offset=400, stop_loss_credit_multiple=1.0, entry_weekday=4)

    vix = pd.read_csv(VIX_PATH)
    vix["date"] = pd.to_datetime(vix["date"]).dt.tz_localize(None).dt.normalize()
    vix_map = vix.set_index("date")["close"]
    res["entry_vix"] = res["entry_date"].map(vix_map)

    baseline = res["net_pnl"].sum()
    print(f"Baseline (no VIX filter): Rs {baseline:,.0f}, n={len(res)}, win_rate={(res['net_pnl']>0).mean()*100:.1f}%")
    print()
    print("VIX bucket breakdown:")
    bins = [0, 13, 18, 22, 100]
    labels = ["<13", "13-18", "18-22", ">22"]
    res["vix_bucket"] = pd.cut(res["entry_vix"], bins=bins, labels=labels)
    grp = res.groupby("vix_bucket", observed=True)["net_pnl"]
    print(pd.DataFrame({"count": grp.count(), "sum": grp.sum(), "mean": grp.mean(), "win_rate": grp.apply(lambda x: (x > 0).mean() * 100)}))
    print()

    print("VIX-cap filter sweep (skip entries above threshold):")
    for thresh in [18, 20, 22, 25]:
        filtered = res[res["entry_vix"] <= thresh]
        skipped = len(res) - len(filtered)
        print(
            f"  VIX<={thresh}: n={len(filtered)} (skipped {skipped}), net=Rs {filtered['net_pnl'].sum():,.0f}, "
            f"win_rate={(filtered['net_pnl']>0).mean()*100:.1f}%"
        )


if __name__ == "__main__":
    main()
