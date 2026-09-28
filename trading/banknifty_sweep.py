"""Sweep entry timing and wing widths for the BankNifty monthly Iron Condor
(1.0x mid-week stop, 5 lots). Days-before-expiry x short offset x wing width.

Usage:
    python banknifty_sweep.py
"""
from __future__ import annotations

import pandas as pd

from banknifty_iron_condor_backtest import DATA_PATH, LOTS, max_drawdown, monthly_schedule
from nifty_iron_condor_backtest import run_iron_condor

DAYS = [10, 15, 21]
SHORTS = [1000, 1500, 2000]
WIDTHS = [500, 1000, 1500]


def main():
    df = pd.read_csv(DATA_PATH, parse_dates=["TradDt", "XpryDt"])
    y1 = df["TradDt"].max() - pd.Timedelta(days=365)
    rows = []
    for days in DAYS:
        schedule = monthly_schedule(df, days)
        for short in SHORTS:
            for width in WIDTHS:
                res = run_iron_condor(
                    df, short, short + width, stop_loss_credit_multiple=1.0, explicit_schedule=schedule,
                )
                r1 = res[res["entry_date"] >= y1]
                rows.append({
                    "days": days, "short": short, "long": short + width, "n": len(res),
                    "net_2y": res["net_pnl"].sum() * LOTS, "win%": (res["net_pnl"] > 0).mean() * 100,
                    "max_dd": max_drawdown(res), "worst": res["net_pnl"].min() * LOTS,
                    "stops": (res["exit_reason"] == "stop_loss").sum(), "net_1y": r1["net_pnl"].sum() * LOTS,
                })
    out = pd.DataFrame(rows)
    pd.set_option("display.width", 200)
    fmt = {c: "{:,.0f}".format for c in ["net_2y", "max_dd", "worst", "net_1y"]}
    fmt["win%"] = "{:.0f}".format
    print(out.to_string(index=False, formatters=fmt))

    print("\n2-year net (Rs lakh) grid, rows = short/long, cols = days before expiry:")
    out["wings"] = out["short"].astype(str) + "/" + out["long"].astype(str)
    print((out.pivot(index="wings", columns="days", values="net_2y") / 1e5).round(2).to_string())
    print("\nMax drawdown (Rs lakh) grid:")
    print((out.pivot(index="wings", columns="days", values="max_dd") / 1e5).round(2).to_string())


if __name__ == "__main__":
    main()
