"""Test two extra filters on the live Nifty ribbon rule (with the market-type
switch), over the last year of 5-minute data.

Base = exactly what nifty_ribbon_signals.py alerts on:
  10-min EMA9/21/50 stack + RSI(14) 60/40 + MACD histogram rising/falling,
  60-pt stop, exit on a 10-min close through EMA21 or 15:10, entries 09:35-14:30,
  max 2 signals a day, 2 pts cost per trade.
  Switch: TRENDING if 4 of the previous 5 days had a first hour >= 120 pts,
  else only after 10:15 and only if today's first hour >= 120.

Filters tested (on top of the base, alone and combined):
  A "after stop"   same: after a stop-loss, no more signals in that direction today
                   all : after a stop-loss, no more signals at all today
  B "into support" skip a SELL that closes 0-X pts ABOVE the day's earlier low
                   (support not broken yet), and a BUY 0-X pts BELOW the day's
                   earlier high; a signal that already broke the level is kept.
                   X = 30/50/75/100
Skipped signals don't use up the 2-a-day limit. Results are shown for the whole
year and split into the first 2/3 and last 1/3 of days (a filter that only
works in one half is probably luck).

Data (pick one):
  --download        fetch ~1 year of NIFTY 50 5-min candles from Kite (needs
                    today's login token in .env; read-only, no orders) and cache it
  --csv PATH        a CSV with date/ts, open, high, low, close
  --yahoo PATH      a Yahoo chart JSON (only 60 days -- for a quick check)
Default: data_cache/NIFTY50_5minute_1y.csv, else data_cache/"NIFTY 50_NSE_5minute.csv".

Usage on the VPS:  ~/venv/bin/python ribbon_filter_test.py --download
         RSI levels:  ~/venv/bin/python ribbon_filter_test.py --rsi   (uses the cached year)
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta

import pandas as pd

import ribbon_trend_backtest as rb
from config import BASE_DIR

NIFTY_TOKEN = 256265
CACHE = BASE_DIR / "data_cache" / "NIFTY50_5minute_1y.csv"
OLD_CACHE = BASE_DIR / "data_cache" / "NIFTY 50_NSE_5minute.csv"
STOP, COST, MAX_SIGNALS = 60.0, 2.0, 2
FIRST_HOUR_MIN, TREND_DAYS, TREND_NEEDED = 120.0, 5, 4


def download() -> pd.DataFrame:
    from dotenv import load_dotenv

    from config import load_config
    from data import get_kite_client
    load_dotenv(BASE_DIR / ".env", override=True)
    kite = get_kite_client(load_config())
    kite.profile()                      # fails fast on a stale token
    end = datetime.now()
    start, rows = end - timedelta(days=380), []
    while start < end:
        stop = min(start + timedelta(days=90), end)
        print(f"Fetching {start.date()} -> {stop.date()}")
        rows += kite.historical_data(NIFTY_TOKEN, start, stop, "5minute")
        start = stop
    d = pd.DataFrame(rows).drop_duplicates("date")
    CACHE.parent.mkdir(exist_ok=True)
    d.to_csv(CACHE, index=False)
    print(f"Saved {len(d)} candles to {CACHE}")
    return d


def normalize(d: pd.DataFrame) -> pd.DataFrame:
    ts = pd.to_datetime(d["ts"] if "ts" in d else d["date"], utc=True).dt.tz_convert("Asia/Kolkata")
    d = d.assign(ts=ts.dt.tz_localize(None))[["ts", "open", "high", "low", "close"]].dropna()
    hm = d.ts.dt.strftime("%H:%M")
    return d[(hm >= "09:15") & (hm < "15:30")].sort_values("ts").drop_duplicates("ts").reset_index(drop=True)


def load_yahoo(path: str) -> pd.DataFrame:
    r = json.load(open(path))["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    return pd.DataFrame({"ts": pd.to_datetime(r["timestamp"], unit="s", utc=True), "open": q["open"],
                         "high": q["high"], "low": q["low"], "close": q["close"]})


def simulate(d: pd.DataFrame, after_stop: str | None = None, near: float | None = None,
             rsi_buy: float = 60, rsi_sell: float = 40) -> pd.DataFrame:
    """Live-rule trades with optional filters. after_stop in (None, 'same', 'all')."""
    b = rb.bars10(d)
    h1 = rb.day_features(d, None)["hour1_range"]
    wide = (h1 >= FIRST_HOUR_MIN).astype(int)
    trending = (wide.rolling(TREND_DAYS).sum().shift(1) >= TREND_NEEDED)
    known = wide.rolling(TREND_DAYS).count().shift(1) >= TREND_DAYS
    out, pos, day_st = [], None, {}
    rows = b.to_dict("records")
    for i in range(1, len(rows)):
        r, p = rows[i], rows[i - 1]
        day = r["day"]
        st = day_st.setdefault(day, {"n": 0, "stopped": set(), "lo": None, "hi": None})
        prev_lo, prev_hi = st["lo"], st["hi"]          # day's low/high BEFORE this candle
        st["lo"] = r["low"] if prev_lo is None else min(prev_lo, r["low"])
        st["hi"] = r["high"] if prev_hi is None else max(prev_hi, r["high"])
        if pos:
            side, entry, stop, pday, et = pos
            px, why = None, None
            if day != pday:
                px, why = p["close"], "eod"
            elif (side > 0 and r["low"] <= stop) or (side < 0 and r["high"] >= stop):
                px, why = stop, "stop"
            elif (side > 0 and r["close"] < r["e21"]) or (side < 0 and r["close"] > r["e21"]):
                px, why = r["close"], "ema21"
            elif r["hhmm"] >= "15:10":
                px, why = r["close"], "15:10"
            if px is None:
                continue
            out.append(dict(day=pday, entry_t=et, side=side, pts=(px - entry) * side - COST, why=why))
            if why == "stop":
                day_st[pday]["stopped"].add(side)
            pos = None
            if day == pday:
                continue
        if not known.get(day, False):
            continue
        hhmm = r["hhmm"]
        if not ("09:35" <= hhmm < "14:30") or st["n"] >= MAX_SIGNALS:
            continue
        if not trending.get(day, False) and not (hhmm >= "10:15" and h1.get(day, 0) >= FIRST_HOUR_MIN):
            continue
        lg = r["close"] > r["e9"] > r["e21"] > r["e50"] and r["rsi"] > rsi_buy and r["mh"] > 0 and r["mh"] > p["mh"]
        sh = r["close"] < r["e9"] < r["e21"] < r["e50"] and r["rsi"] < rsi_sell and r["mh"] < 0 and r["mh"] < p["mh"]
        if not (lg or sh):
            continue
        side = 1 if lg else -1
        if after_stop == "all" and st["stopped"] or after_stop == "same" and side in st["stopped"]:
            continue
        if near is not None and prev_lo is not None:
            gap = r["close"] - prev_lo if side < 0 else prev_hi - r["close"]
            if 0 <= gap < near:
                continue
        pos = (side, r["close"], r["close"] - side * STOP, day, hhmm)
        st["n"] += 1
    return pd.DataFrame(out, columns=["day", "entry_t", "side", "pts", "why"])


def stats(t: pd.DataFrame) -> dict:
    if t.empty:
        return dict(n=0, total=0, avg=0.0, win="-", worst_day=0, max_dd=0)
    eq = t.pts.cumsum()
    return dict(n=len(t), total=round(t.pts.sum()), avg=round(t.pts.mean(), 1), win=f"{(t.pts > 0).mean():.0%}",
                worst_day=round(t.groupby("day").pts.sum().min()), max_dd=round((eq.cummax() - eq).max()))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--csv")
    ap.add_argument("--yahoo")
    ap.add_argument("--rsi", action="store_true", help="compare RSI levels instead of filters A/B")
    args = ap.parse_args()
    if args.download:
        raw = download()
    elif args.yahoo:
        raw = load_yahoo(args.yahoo)
    else:
        path = args.csv or (CACHE if CACHE.exists() else OLD_CACHE)
        raw = pd.read_csv(path)
    d = normalize(raw)
    days = sorted(set(d.ts.dt.date))
    cut = days[int(len(days) * 2 / 3)]
    if args.rsi:
        variants = [(f"RSI {hi}/{lo}" + (" + A (LIVE NOW)" if (hi, a) == (60, "same") else " + A" if a else ""),
                     a, None, hi, lo)
                    for a in ("same", None) for hi, lo in ((65, 35), (60, 40), (58, 42), (55, 45), (52, 48))]
    else:
        variants = [("BASE (live rule today)", None, None, 60, 40)]
        variants += [(f"A: after a stop, block {m}", m, None, 60, 40) for m in ("same", "all")]
        variants += [(f"B: skip {x} pts above the low / below the high", None, x, 60, 40) for x in (30, 50, 75, 100)]
        variants += [(f"A({m}) + B({x})", m, x, 60, 40) for m in ("same", "all") for x in (50, 75)]
    rows = []
    for name, m, x, hi, lo in variants:
        t = simulate(d, m, x, hi, lo)
        a, tr, te = stats(t), stats(t[t.day < cut]), stats(t[t.day >= cut])
        rows.append({"version": name, **a, "first2/3": tr["total"], "last1/3": te["total"]})
    pd.set_option("display.width", 200)
    print(f"\n{len(days)} days {days[0]} .. {days[-1]} (split at {cut}); points per 1 Nifty unit, after 2 pts cost")
    print(pd.DataFrame(rows).to_string(index=False))
    base = simulate(d)
    print("\nBase rule, last 10 signals:")
    print(base.tail(10).round(1).to_string(index=False))


if __name__ == "__main__":
    main()
