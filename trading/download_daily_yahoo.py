"""Download ~5 years of daily OHLCV for the cached NSE100 universe from Yahoo
Finance (split-adjusted) into data_cache/daily/<SYMBOL>.csv. Resumable: skips
symbols already downloaded today."""
from __future__ import annotations

import datetime as dt
import glob
import json
import os
import time
import urllib.parse
import urllib.request

import pandas as pd

from config import BASE_DIR

CACHE = BASE_DIR / "data_cache"
OUT = CACHE / "daily"
URL = "https://query2.finance.yahoo.com/v8/finance/chart/{sym}?range=5y&interval=1d"


def universe() -> list[str]:
    return sorted(os.path.basename(p).split("_NSE_")[0] for p in glob.glob(str(CACHE / "*_NSE_5minute.csv")))


def fetch(symbol: str) -> pd.DataFrame:
    req = urllib.request.Request(URL.format(sym=urllib.parse.quote(symbol + ".NS")),
                                 headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        res = json.load(resp)["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    df = pd.DataFrame({"date": pd.to_datetime(res["timestamp"], unit="s").tz_localize("UTC").tz_convert("Asia/Kolkata").date,
                       "open": q["open"], "high": q["high"], "low": q["low"], "close": q["close"], "volume": q["volume"]})
    return df.dropna(subset=["open", "high", "low", "close"]).drop_duplicates("date", keep="last")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    today = dt.date.today()
    for sym in universe():
        path = OUT / f"{sym}.csv"
        if path.exists() and dt.date.fromtimestamp(path.stat().st_mtime) == today:
            continue
        for attempt in range(4):
            try:
                df = fetch(sym)
                df.to_csv(path, index=False)
                print(f"{sym}: {len(df)} days {df['date'].iloc[0]} .. {df['date'].iloc[-1]}")
                break
            except Exception as exc:
                print(f"{sym}: attempt {attempt + 1} failed ({exc})")
                time.sleep(2 ** attempt * 2)
        time.sleep(0.5)


if __name__ == "__main__":
    main()
