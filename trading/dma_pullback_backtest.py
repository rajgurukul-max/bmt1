"""NSE100 '200 DMA touch -> buy, exit at 50 DMA' backtest on daily data
(data_cache/daily, from download_daily_yahoo.py).

Rules (no look-ahead -- levels are the previous day's moving averages):
  - Setup: yesterday's close was ABOVE its 200 DMA.
  - Entry: today's low touches yesterday's 200 DMA -> buy at that level
    (or at the open if the stock gaps below it).
  - Exit: the first later day whose high reaches the previous day's 50 DMA
    -> sell at that level (or at the open if it gaps above it).
  - No stop loss (as asked). Trades still open at the end are marked at the
    last close and reported separately.
  - After an exit, a new entry needs the stock to close above its 200 DMA again.
  - Costs: 0.25% round trip (delivery STT, exchange, GST, stamp, slippage).

Two variants are reported:
  all      -- every 200 DMA touch
  uptrend  -- only touches where the 50 DMA is above the 200 DMA (a pullback
              in an uptrend: the 50 DMA exit target is above the entry)
"""
from __future__ import annotations

import glob
import os

import numpy as np
import pandas as pd

from config import BASE_DIR

DAILY = BASE_DIR / "data_cache" / "daily"
COST = 0.0025
MIN_HISTORY = 200


def trades_for(sym: str, df: pd.DataFrame, uptrend_only: bool) -> list[dict]:
    df = df.copy()
    df["sma50"] = df["close"].rolling(50).mean().shift(1)
    df["sma200"] = df["close"].rolling(200).mean().shift(1)
    df["prev_close"] = df["close"].shift(1)
    out, pos, armed = [], None, False
    for row in df.itertuples():
        if np.isnan(row.sma200):
            continue
        if pos is None:
            if row.prev_close > row.sma200:
                armed = True
            if armed and row.low <= row.sma200 and (not uptrend_only or row.sma50 > row.sma200):
                entry = min(row.open, row.sma200)
                pos = dict(symbol=sym, entry_date=row.date, entry=entry, low=row.low, target_at_entry=row.sma50)
                armed = False
            continue
        pos["low"] = min(pos["low"], row.low)
        if row.high >= row.sma50:
            exit_px = max(row.open, row.sma50)
            out.append(dict(pos, exit_date=row.date, exit=exit_px, open=False))
            pos = None
    if pos is not None:
        last = df.iloc[-1]
        out.append(dict(pos, exit_date=last["date"], exit=last["close"], open=True))
    return out


def summarize(t: pd.DataFrame, label: str) -> None:
    closed, still_open = t[~t["open"]], t[t["open"]]
    print(f"\n=== {label}: {len(t)} trades on {t['symbol'].nunique()} stocks "
          f"({len(closed)} closed, {len(still_open)} still open) ===")
    if len(closed):
        w = closed["ret"] > 0
        print(f"closed: win rate {w.mean():.0%}, avg return {closed['ret'].mean():+.2%}, "
              f"median {closed['ret'].median():+.2%}, avg win {closed.loc[w, 'ret'].mean():+.2%}, "
              f"avg loss {closed.loc[~w, 'ret'].mean():+.2%}")
        print(f"        avg hold {closed['days'].mean():.0f} days (median {closed['days'].median():.0f}), "
              f"worst dip while holding {closed['mae'].min():.1%} (avg {closed['mae'].mean():.1%})")
        print(f"        Rs 1L per trade -> total Rs {closed['ret'].sum() * 1e5:,.0f}")
    if len(still_open):
        print(f"open:   {len(still_open)} trades, avg mark-to-market {still_open['ret'].mean():+.2%}, "
              f"worst {still_open['ret'].min():+.1%}, avg days held {still_open['days'].mean():.0f}")


def main() -> None:
    data = {}
    for p in sorted(glob.glob(str(DAILY / "*.csv"))):
        df = pd.read_csv(p, parse_dates=["date"])
        if len(df) >= MIN_HISTORY + 50:
            data[os.path.basename(p)[:-4]] = df
    for uptrend_only, label in ((False, "ALL 200 DMA touches"), (True, "UPTREND only (50 DMA > 200 DMA)")):
        rows = [tr for sym, df in data.items() for tr in trades_for(sym, df, uptrend_only)]
        t = pd.DataFrame(rows)
        t["ret"] = t["exit"] / t["entry"] - 1 - COST
        t["days"] = (t["exit_date"] - t["entry_date"]).dt.days
        t["mae"] = t["low"] / t["entry"] - 1
        summarize(t, label)
        recent = t[t["entry_date"] >= t["entry_date"].max() - pd.Timedelta(days=730)]
        summarize(recent, label + " -- last 2 years only")
        tag = "uptrend" if uptrend_only else "all"
        t.to_csv(BASE_DIR / "reports" / f"dma_pullback_trades_{tag}.csv", index=False)
        per = (t[~t["open"]].groupby("symbol")
               .agg(trades=("ret", "size"), win_rate=("ret", lambda r: (r > 0).mean()),
                    avg_ret=("ret", "mean"), total_ret=("ret", "sum"), worst_dip=("mae", "min"))
               .sort_values("total_ret", ascending=False))
        per.to_csv(BASE_DIR / "reports" / f"dma_pullback_by_stock_{tag}.csv")
        fmt = per.assign(win_rate=per.win_rate.map("{:.0%}".format), avg_ret=per.avg_ret.map("{:+.1%}".format),
                         total_ret=per.total_ret.map("{:+.1%}".format), worst_dip=per.worst_dip.map("{:.0%}".format))
        print("best 10:\n" + fmt.head(10).to_string())
        print("worst 10:\n" + fmt.tail(10).to_string())


if __name__ == "__main__":
    main()
