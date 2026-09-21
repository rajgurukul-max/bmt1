"""Analyze ANGELONE's first-hour (09:15-10:15) price action using 1-min candles.

For each trading day in the lookback window, computes:
  - open/high/low/close of the 09:15-10:15 window
  - the exact time the high and low occurred
  - which one came first (high_first / low_first)
  - RSI(14) and EMA(20) value at the moment of the high and of the low
    (indicators computed continuously across the whole chronological series,
    not reset daily, so they're properly warmed up by 09:15 each day)

Outputs a row-per-day CSV plus summary averages across the period, meant as
raw exploratory material for designing a new strategy hypothesis -- this
script does not implement or backtest a strategy itself.

Usage:
    python hour1_analysis.py [--days 90] [--rsi-period 14] [--ema-period 20]
"""
from __future__ import annotations

import argparse
from datetime import time as dtime

import numpy as np
import pandas as pd

from config import load_config
from data import update_cache, load_cached_candles

SYMBOL = "ANGELONE"
EXCHANGE = "NSE"
WINDOW_START = dtime(9, 15)
WINDOW_END = dtime(10, 15)  # exclusive upper bound on candle start time


def compute_rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    rsi[avg_loss == 0] = 100
    return rsi


def compute_ema(close: pd.Series, period: int) -> pd.Series:
    return close.ewm(span=period, adjust=False, min_periods=period).mean()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=90, help="Calendar days of 1-min history to fetch.")
    parser.add_argument("--rsi-period", type=int, default=14)
    parser.add_argument("--ema-period", type=int, default=20)
    parser.add_argument("--refresh", action="store_true", help="Re-download instead of using cache.")
    args = parser.parse_args()

    cfg = load_config()
    cfg.data.interval = "minute"
    cfg.data.history_days = args.days
    cfg.data.request_chunk_days = 55  # Kite caps 'minute' interval at ~60 days/request

    print(f"Fetching {args.days} days of 1-min {SYMBOL} candles (interval=minute)...")
    df = update_cache(cfg, refresh_all=args.refresh, symbol=SYMBOL, exchange=EXCHANGE)
    if df.empty:
        raise SystemExit("No 1-min data available.")

    df = df.sort_values("date").reset_index(drop=True)
    print(f"Have {len(df)} candles from {df['date'].min()} to {df['date'].max()}")

    df["rsi"] = compute_rsi(df["close"], args.rsi_period)
    df["ema"] = compute_ema(df["close"], args.ema_period)
    df["trading_date"] = df["date"].dt.date
    df["t"] = df["date"].dt.time

    rows = []
    for day, day_df in df.groupby("trading_date"):
        window = day_df[(day_df["t"] >= WINDOW_START) & (day_df["t"] < WINDOW_END)]
        if window.empty or window["rsi"].isna().all():
            continue

        open_price = window.iloc[0]["open"]
        close_price = window.iloc[-1]["close"]

        high_row = window.loc[window["high"].idxmax()]
        low_row = window.loc[window["low"].idxmin()]

        high_val, high_time = high_row["high"], high_row["date"]
        low_val, low_time = low_row["low"], low_row["date"]
        sequence = "HIGH_FIRST" if high_time < low_time else ("LOW_FIRST" if low_time < high_time else "SAME_BAR")

        rows.append({
            "date": day,
            "open": round(open_price, 2),
            "high": round(high_val, 2),
            "high_time": high_time.strftime("%H:%M"),
            "low": round(low_val, 2),
            "low_time": low_time.strftime("%H:%M"),
            "close": round(close_price, 2),
            "sequence": sequence,
            "rsi_at_high": round(high_row["rsi"], 1) if pd.notna(high_row["rsi"]) else None,
            "rsi_at_low": round(low_row["rsi"], 1) if pd.notna(low_row["rsi"]) else None,
            "ema_at_high": round(high_row["ema"], 2) if pd.notna(high_row["ema"]) else None,
            "ema_at_low": round(low_row["ema"], 2) if pd.notna(low_row["ema"]) else None,
        })

    result = pd.DataFrame(rows)
    out_path = cfg.data.cache_dir.parent / "reports" / "hour1_analysis.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(out_path, index=False)

    pd.set_option("display.width", 200)
    pd.set_option("display.max_rows", 200)
    print(f"\n{len(result)} trading days analyzed. Full table saved to {out_path}\n")
    print(result.to_string(index=False))

    def time_to_minutes(t: str) -> int:
        h, m = map(int, t.split(":"))
        return (h - 9) * 60 + (m - 15)

    high_minutes = result["high_time"].apply(time_to_minutes)
    low_minutes = result["low_time"].apply(time_to_minutes)

    def minutes_to_time(m: float) -> str:
        total = 9 * 60 + 15 + m
        return f"{int(total // 60):02d}:{int(total % 60):02d}"

    print("\n" + "=" * 60)
    print("SUMMARY across", len(result), "days")
    print("=" * 60)
    print(f"Avg high time : {minutes_to_time(high_minutes.mean())}  (median {minutes_to_time(high_minutes.median())})")
    print(f"Avg low time  : {minutes_to_time(low_minutes.mean())}  (median {minutes_to_time(low_minutes.median())})")
    seq_counts = result["sequence"].value_counts()
    print(f"Sequence      : {dict(seq_counts)}  ({(seq_counts.get('HIGH_FIRST', 0) / len(result) * 100):.1f}% high-first)")
    print(f"Avg RSI@high  : {result['rsi_at_high'].mean():.1f}   Avg RSI@low : {result['rsi_at_low'].mean():.1f}")
    print(f"Avg EMA@high  : {result['ema_at_high'].mean():.2f}   Avg EMA@low : {result['ema_at_low'].mean():.2f}")
    print(f"Avg range     : {(result['high'] - result['low']).mean():.2f} pts "
          f"({((result['high'] - result['low']) / result['open'] * 100).mean():.2f}% of open)")


if __name__ == "__main__":
    main()
