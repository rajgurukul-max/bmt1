"""BankNifty monthly Iron Condor: sell CE/PE 1000 pts OTM, buy CE/PE 2500 pts
OTM, entered ~15 calendar days before each MONTHLY expiry (BankNifty weeklies
were discontinued in Nov 2024), held to expiry with an optional mid-week stop.
1000/2500 chosen over the original 1500/2500 after banknifty_sweep.py: higher
net (Rs 5.18L vs 3.07L over 2y, 5 lots) at the cost of a deeper drawdown
(-Rs 1.73L vs -0.99L) and worst month (-Rs 1.12L vs -0.69L).

Final stop: fixed Rs 25k loss on the whole 5-lot position, replacing the 1.0x
credit stop (Rs 5.37L net, max drawdown -Rs 82k vs -Rs 1.73L). The backtest
checks it at daily closes, so stopped trades realize -Rs 30k to -58k on gap
days; a live version should monitor intraday, expiry day included.

Entry day = latest trading day at least 15 calendar days before the monthly
expiry. Monthly expiry = last expiry date within each calendar month (the
early months of the data still list weekly contracts alongside it).

Data: data_cache/BANKNIFTY_OPTIONS_bhavcopy.csv, from
    python download_stock_options.py BANKNIFTY --index

Usage:
    python banknifty_iron_condor_backtest.py
"""
from __future__ import annotations

import pandas as pd

from nifty_iron_condor_backtest import run_iron_condor

DATA_PATH = "data_cache/BANKNIFTY_OPTIONS_bhavcopy.csv"
SHORT_OFFSET = 1000
LONG_OFFSET = 2500
DAYS_BEFORE = 15
LOTS = 5
STOP_LOSS_RUPEES = 25000  # whole position (all LOTS)


def monthly_schedule(df: pd.DataFrame, days_before: int) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    trade_days = sorted(df["TradDt"].unique())
    last_day = trade_days[-1]
    settled = sorted(e for e in df["XpryDt"].unique() if e <= last_day and e in set(trade_days))
    monthly = pd.Series(settled).groupby(pd.Series(settled).dt.to_period("M")).max().tolist()
    schedule = []
    for expiry in monthly:
        candidates = [d for d in trade_days if (expiry - d).days >= days_before]
        if candidates:
            schedule.append((candidates[-1], expiry))
    return schedule


def max_drawdown(res: pd.DataFrame) -> float:
    cum = (res.sort_values("entry_date")["net_pnl"].values * LOTS).cumsum()
    return (cum - pd.Series(cum).cummax()).min()


def main():
    df = pd.read_csv(DATA_PATH, parse_dates=["TradDt", "XpryDt"])
    schedule = monthly_schedule(df, DAYS_BEFORE)
    print(f"{len(schedule)} monthly cycles, {df['TradDt'].min().date()} to {df['TradDt'].max().date()}")

    end = df["TradDt"].max()
    windows = {"6m": end - pd.Timedelta(days=182), "1y": end - pd.Timedelta(days=365), "2y": df["TradDt"].min()}

    variants = [
        (f"Rs {STOP_LOSS_RUPEES // 1000}k stop (final)", dict(stop_loss_amount=STOP_LOSS_RUPEES / LOTS)),
        ("1.0x credit stop", dict(stop_loss_credit_multiple=1.0)),
        ("no stop", dict()),
    ]
    for i, (label, kw) in enumerate(variants):
        res = run_iron_condor(df, SHORT_OFFSET, LONG_OFFSET, explicit_schedule=schedule, **kw)
        print(f"\n=== {SHORT_OFFSET}/{LONG_OFFSET}, {DAYS_BEFORE}d before monthly expiry, {label}, {LOTS} lots ===")
        for w, start in windows.items():
            r = res[res["entry_date"] >= start]
            print(
                f"  {w}: n={len(r):>2}  net=Rs {r['net_pnl'].sum() * LOTS:>10,.0f}  "
                f"win={(r['net_pnl'] > 0).mean() * 100:5.1f}%  max_dd=Rs {max_drawdown(r):>10,.0f}  "
                f"worst=Rs {r['net_pnl'].min() * LOTS:>9,.0f}"
            )
        if i == 0:
            show = res[["entry_date", "expiry", "exit_reason", "cmp", "lot_size", "net_credit_per_share", "net_pnl"]].copy()
            show["net_pnl_5lots"] = (show.pop("net_pnl") * LOTS).round(0)
            show["net_credit_per_share"] = show["net_credit_per_share"].round(1)
            print(show.to_string(index=False))


if __name__ == "__main__":
    main()
