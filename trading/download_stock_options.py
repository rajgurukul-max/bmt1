"""Download real historical NSE single-stock options bhavcopy data for a given
symbol (e.g. RELIANCE, ITC), mirrored from
github.com/SantoshSrinivas79/NSE-FNO-Data-bank (nseindia.com itself is blocked
by Akamai bot protection from this environment; this GitHub mirror republishes
the same real settlement data and is not blocked).

Unlike NIFTY/SENSEX, single-stock F&O in India has MONTHLY expiry only (no
weekly), and FinInstrmTp for stock options is "STO" (vs "IDO" for index
options).

Usage:
    python download_stock_options.py RELIANCE [--start YYYY-MM-DD] [--end YYYY-MM-DD]
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

URL_TMPL = (
    "https://raw.githubusercontent.com/SantoshSrinivas79/NSE-FNO-Data-bank/"
    "main/data/{yyyy}/{mm}/BhavCopy_NSE_FO_0_0_0_{date}_F_0000.csv.zip"
)


def fetch_day(date: pd.Timestamp, symbol: str) -> pd.DataFrame | None:
    url = URL_TMPL.format(yyyy=date.strftime("%Y"), mm=date.strftime("%m"), date=date.strftime("%Y%m%d"))
    try:
        resp = requests.get(url, timeout=20)
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            name = zf.namelist()[0]
            with zf.open(name) as fh:
                df = pd.read_csv(fh)
    except (zipfile.BadZipFile, IndexError):
        return None
    df = df[(df["TckrSymb"] == symbol) & (df["FinInstrmTp"] == "STO")]
    if df.empty:
        return None
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol", help="NSE stock symbol, e.g. RELIANCE")
    ap.add_argument("--start", default=None, help="YYYY-MM-DD, default = 2 years ago")
    ap.add_argument("--end", default=None, help="YYYY-MM-DD, default = today")
    args = ap.parse_args()
    symbol = args.symbol.upper()

    cache_path = Path(f"data_cache/{symbol}_OPTIONS_bhavcopy.csv")

    end = pd.Timestamp(args.end) if args.end else pd.Timestamp.today().normalize()
    start = pd.Timestamp(args.start) if args.start else end - pd.Timedelta(days=730)

    cache_path.parent.mkdir(exist_ok=True)

    done_dates: set[pd.Timestamp] = set()
    if cache_path.exists():
        existing = pd.read_csv(cache_path, parse_dates=["TradDt"])
        done_dates = set(existing["TradDt"].unique())
        print(f"Resuming: {len(done_dates)} days already cached", file=sys.stderr)

    all_days = pd.bdate_range(start, end)
    todo = [d for d in all_days if d not in done_dates]
    print(f"{len(todo)} of {len(all_days)} days remain to fetch", file=sys.stderr)

    frames = []
    ok, empty = 0, 0
    header_written = cache_path.exists()
    for i, d in enumerate(todo):
        df = fetch_day(d, symbol)
        if df is None:
            empty += 1
        else:
            frames.append(df)
            ok += 1
        if len(frames) >= 25 or (i == len(todo) - 1 and frames):
            chunk = pd.concat(frames, ignore_index=True)
            chunk["TradDt"] = pd.to_datetime(chunk["TradDt"])
            chunk["XpryDt"] = pd.to_datetime(chunk["XpryDt"])
            chunk.to_csv(cache_path, mode="a", header=not header_written, index=False)
            header_written = True
            frames = []
        if (i + 1) % 25 == 0 or i == len(todo) - 1:
            print(f"  ...{i+1}/{len(todo)} days fetched (ok={ok}, empty={empty})", file=sys.stderr)
        time.sleep(0.2)

    if not header_written:
        print("No data downloaded.", file=sys.stderr)
        sys.exit(1)

    final = pd.read_csv(cache_path, parse_dates=["TradDt"])
    print(f"Saved {len(final)} rows across {final['TradDt'].nunique()} trading days to {cache_path}")


if __name__ == "__main__":
    main()
