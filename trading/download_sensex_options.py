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

    all_days = pd.bdate_range(start, end)
    frames = []
    ok, empty, fail = 0, 0, 0
    for i, d in enumerate(all_days):
        df = fetch_day(d)
        if df is None:
            empty += 1
        else:
            frames.append(df)
            ok += 1
        if (i + 1) % 25 == 0:
            print(f"  ...{i+1}/{len(all_days)} days processed (ok={ok}, empty={empty})", file=sys.stderr)
        time.sleep(0.15)

    if not frames:
        print("No data downloaded.", file=sys.stderr)
        sys.exit(1)

    combined = pd.concat(frames, ignore_index=True)
    combined["TradDt"] = pd.to_datetime(combined["TradDt"])
    combined["XpryDt"] = pd.to_datetime(combined["XpryDt"])
    CACHE_PATH.parent.mkdir(exist_ok=True)
    combined.to_csv(CACHE_PATH, index=False)
    print(f"Saved {len(combined)} rows across {combined['TradDt'].nunique()} trading days to {CACHE_PATH}")


if __name__ == "__main__":
    main()
