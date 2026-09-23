"""Download real historical BSE SENSEX options bhavcopy data directly from BSE's
own archive (bseindia.com), which -- unlike nseindia.com -- is NOT blocked by
Akamai bot protection from this environment. Filters to TckrSymb == SENSEX and
caches the combined result the same way download_nifty_options.py does for NIFTY.

Usage:
    python download_sensex_options.py [--start YYYY-MM-DD] [--end YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import io
import sys
import time
import zipfile
from pathlib import Path

import pandas as pd
import requests

CACHE_PATH = Path("data_cache/SENSEX_OPTIONS_bhavcopy.csv")
URL_TMPL = "https://www.bseindia.com/download/BhavCopy/Derivative/BhavCopy_BSE_FO_0_0_0_{date}_F_0000.CSV"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}


def fetch_day(date: pd.Timestamp) -> pd.DataFrame | None:
    url = URL_TMPL.format(date=date.strftime("%Y%m%d"))
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    text = resp.text
    if not text.startswith("TradDt"):
        return None  # weekend/holiday -> BSE serves an HTML page instead
    df = pd.read_csv(io.StringIO(text))
    df = df[(df["TckrSymb"] == "SENSEX") & (df["FinInstrmTp"].isin(["IDO"]))]
    if df.empty:
        return None
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=None, help="YYYY-MM-DD, default = 2 years ago")
    ap.add_argument("--end", default=None, help="YYYY-MM-DD, default = today")
    args = ap.parse_args()

    end = pd.Timestamp(args.end) if args.end else pd.Timestamp.today().normalize()
    start = pd.Timestamp(args.start) if args.start else end - pd.Timedelta(days=730)

    CACHE_PATH.parent.mkdir(exist_ok=True)

    done_dates: set[pd.Timestamp] = set()
    if CACHE_PATH.exists():
        existing = pd.read_csv(CACHE_PATH, parse_dates=["TradDt"])
        done_dates = set(existing["TradDt"].unique())
        print(f"Resuming: {len(done_dates)} days already cached", file=sys.stderr)

    all_days = pd.bdate_range(start, end)
    todo = [d for d in all_days if d not in done_dates]
    print(f"{len(todo)} of {len(all_days)} days remain to fetch", file=sys.stderr)

    frames = []
    ok, empty = 0, 0
    header_written = CACHE_PATH.exists()
    for i, d in enumerate(todo):
        df = fetch_day(d)
        if df is None:
            empty += 1
        else:
            frames.append(df)
            ok += 1
        if len(frames) >= 25 or (i == len(todo) - 1 and frames):
            chunk = pd.concat(frames, ignore_index=True)
            chunk["TradDt"] = pd.to_datetime(chunk["TradDt"])
            chunk["XpryDt"] = pd.to_datetime(chunk["XpryDt"])
            chunk.to_csv(CACHE_PATH, mode="a", header=not header_written, index=False)
            header_written = True
            frames = []
        if (i + 1) % 25 == 0 or i == len(todo) - 1:
            print(f"  ...{i+1}/{len(todo)} days fetched (ok={ok}, empty={empty})", file=sys.stderr)
        time.sleep(0.15)

    if not header_written:
        print("No data downloaded.", file=sys.stderr)
        sys.exit(1)

    final = pd.read_csv(CACHE_PATH, parse_dates=["TradDt"])
    print(f"Saved {len(final)} rows across {final['TradDt'].nunique()} trading days to {CACHE_PATH}")


if __name__ == "__main__":
    main()
