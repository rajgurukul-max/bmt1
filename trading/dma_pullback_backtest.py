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


def trades_for(sym: str, df: pd.DataFrame, uptrend_only: bool, stop_pct: float | None = None,
               max_days: int | None = None) -> list[dict]:
    """stop_pct: exit when the low falls stop_pct below entry (at that level, or
    the open if it gaps through), checked from the entry day itself and BEFORE
    the target on the same day (conservative). max_days: exit at the close of
    the first day max_days or more calendar days after entry."""
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
                if stop_pct is not None and row.low <= entry * (1 - stop_pct):
                    out.append(dict(pos, exit_date=row.date, exit=entry * (1 - stop_pct), open=False, reason="stop"))
                    pos = None
            continue
        pos["low"] = min(pos["low"], row.low)
        stop_px = None if stop_pct is None else pos["entry"] * (1 - stop_pct)
        if stop_px is not None and row.low <= stop_px:
            out.append(dict(pos, exit_date=row.date, exit=min(row.open, stop_px), open=False, reason="stop"))
            pos = None
        elif row.high >= row.sma50:
            out.append(dict(pos, exit_date=row.date, exit=max(row.open, row.sma50), open=False, reason="target"))
            pos = None
        elif max_days is not None and (row.date - pos["entry_date"]).days >= max_days:
            out.append(dict(pos, exit_date=row.date, exit=row.close, open=False, reason="time"))
            pos = None
    if pos is not None:
        last = df.iloc[-1]
        out.append(dict(pos, exit_date=last["date"], exit=last["close"], open=True, reason="open"))
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


def run_grid(data: dict, symbols: list[str] | None, label: str) -> None:
    """Uptrend variant under each stop / time-limit combination."""
    rows = []
    for stop in (None, 0.08, 0.10, 0.15):
        for max_days in (None, 30):
            t = pd.DataFrame([tr for sym, df in data.items() if symbols is None or sym in symbols
                              for tr in trades_for(sym, df, True, stop, max_days)])
            t["ret"] = t["exit"] / t["entry"] - 1 - COST
            t["days"] = (t["exit_date"] - t["entry_date"]).dt.days
            recent = t[t["entry_date"] >= t["entry_date"].max() - pd.Timedelta(days=730)]
            rows.append({
                "stop": "none" if stop is None else f"-{stop:.0%}",
                "time limit": "none" if max_days is None else f"{max_days}d",
                "trades": len(t), "win rate": f"{(t.ret > 0).mean():.0%}",
                "avg/trade": f"{t.ret.mean():+.2%}", "worst": f"{t.ret.min():+.0%}",
                "avg hold d": round(t.days.mean()), "stopped": int((t.reason == "stop").sum()),
                "timed out": int((t.reason == "time").sum()),
                "total Rs (1L/trade)": f"{t.ret.sum() * 1e5:,.0f}",
                "last 2y Rs": f"{recent.ret.sum() * 1e5:,.0f}",
            })
    print(f"\n=== {label}: uptrend touches, totals include open trades at last close ===")
    print(pd.DataFrame(rows).to_string(index=False))


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




def stops_main() -> None:
    data = {}
    for p in sorted(glob.glob(str(DAILY / "*.csv"))):
        df = pd.read_csv(p, parse_dates=["date"])
        if len(df) >= MIN_HISTORY + 50:
            data[os.path.basename(p)[:-4]] = df
    run_grid(data, ["ANGELONE"], "ANGELONE")
    run_grid(data, None, f"ALL {len(data)} NSE100 stocks")


if __name__ == "__main__":
    import sys
    stops_main() if "--stops" in sys.argv else main()
