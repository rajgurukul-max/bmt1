"""Download India VIX daily history via Kite, used to test whether filtering
the validated Nifty Iron Condor by entry-day VIX level improves results (see
vix_filter_analysis.py). INDIA VIX instrument token is fixed (264969, NSE
INDICES segment).

Usage:
    python download_india_vix.py
"""
from __future__ import annotations

import datetime as dt

import pandas as pd
from kiteconnect import KiteConnect

import config

VIX_TOKEN = 264969
CACHE_PATH = "data_cache/INDIA_VIX_daily.csv"


def main():
    cfg = config.load_config()
    kite = KiteConnect(api_key=cfg.zerodha.api_key)
    kite.set_access_token(cfg.zerodha.access_token)

    end = dt.date.today()
    start = end - dt.timedelta(days=730)
    all_data = []
    cur = start
    while cur < end:
        chunk_end = min(cur + dt.timedelta(days=90), end)
        all_data.extend(kite.historical_data(VIX_TOKEN, cur, chunk_end, "day"))
        cur = chunk_end + dt.timedelta(days=1)

    df = pd.DataFrame(all_data)
    df.to_csv(CACHE_PATH, index=False)
    print(f"Saved {len(df)} rows to {CACHE_PATH}")


if __name__ == "__main__":
    main()
