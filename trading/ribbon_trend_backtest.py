"""Intraday Nifty 'EMA ribbon' trend rule, with and without trending-day filters.

Rule (10-minute candles, indicators carried across days like a chart):
  long  when close > EMA9 > EMA21 > EMA50, RSI(14) > 60, MACD(12,26,9)
        histogram > 0 and rising; short is the mirror (RSI < 40)
  stop 60 points; exit when a candle closes back through EMA21, or 15:10
  entries 09:35-14:30, at most 2 trades a day; 2 points cost per round trip

Trending-day filters, all known BEFORE the trade (no hindsight):
  prev_range    previous day's high-low range >= X points
  avg5_range    average high-low range of the previous 5 days >= X
  vix           previous day's India VIX close >= X
  gap           today's opening gap >= X% (either direction)
  hour1_range   first hour (09:15-10:15) range >= X points; entries only after 10:15
Plus one HINDSIGHT row (today's own open-to-close move) to show the ceiling --
it cannot be traded.

Data: data_cache/"NIFTY 50_NSE_5minute.csv" (Sep 2025 - Sep 2026) extended with
recent Yahoo 5-minute bars if --recent is given; VIX from a Yahoo chart JSON.
Thresholds are picked on the first 2/3 of days and judged on the last 1/3.

Usage: python ribbon_trend_backtest.py [--recent nifty_5m_recent.csv] [--vix vix.json]
"""
from __future__ import annotations

import argparse
import json

import pandas as pd

COST, STOP, MAX_TRADES = 2.0, 60.0, 2


def load(recent: str | None) -> pd.DataFrame:
    d = pd.read_csv("data_cache/NIFTY 50_NSE_5minute.csv")
    d["ts"] = pd.to_datetime(d["date"])
    d = d[["ts", "open", "high", "low", "close"]]
    if recent:
        r = pd.read_csv(recent, parse_dates=["ts"])
        d = pd.concat([d, r[r.ts > d.ts.max()][["ts", "open", "high", "low", "close"]]], ignore_index=True)
    return d


def bars10(d: pd.DataFrame) -> pd.DataFrame:
    b = d.set_index("ts").resample("10min", origin="start_day", offset="15min").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna().reset_index()
    b["day"] = b.ts.dt.date
    b["hhmm"] = b.ts.dt.strftime("%H:%M")
    c = b.close
    for n in (9, 21, 50):
        b[f"e{n}"] = c.ewm(span=n, adjust=False).mean()
    delta = c.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    dn = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    b["rsi"] = 100 - 100 / (1 + up / dn)
    macd = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    b["mh"] = macd - macd.ewm(span=9, adjust=False).mean()
    return b


def trades(b: pd.DataFrame) -> pd.DataFrame:
    """All trades of the base rule; each row knows its day, entry time and P&L."""
    out, pos, per_day = [], None, {}
    rows = b.to_dict("records")
    for i in range(1, len(rows)):
        r, p = rows[i], rows[i - 1]
        if pos:
            side, entry, stop, day, et = pos
            px = None
            if (side > 0 and r["low"] <= stop) or (side < 0 and r["high"] >= stop):
                px = stop
            elif (side > 0 and r["close"] < r["e21"]) or (side < 0 and r["close"] > r["e21"]):
                px = r["close"]
            elif r["hhmm"] >= "15:10" or r["day"] != day:
                px = r["close"] if r["day"] == day else p["close"]
            if px is not None:
                out.append(dict(day=day, entry_t=et, side=side, pts=(px - entry) * side - COST))
                pos = None
            continue
        if not ("09:35" <= r["hhmm"] < "14:30") or per_day.get(r["day"], 0) >= MAX_TRADES:
            continue
        lg = r["close"] > r["e9"] > r["e21"] > r["e50"] and r["rsi"] > 60 and r["mh"] > 0 and r["mh"] > p["mh"]
        sh = r["close"] < r["e9"] < r["e21"] < r["e50"] and r["rsi"] < 40 and r["mh"] < 0 and r["mh"] < p["mh"]
        if lg or sh:
            side = 1 if lg else -1
            pos = (side, r["close"], r["close"] - side * STOP, r["day"], r["hhmm"])
            per_day[r["day"]] = per_day.get(r["day"], 0) + 1
    return pd.DataFrame(out)


def day_features(d: pd.DataFrame, vix: pd.Series | None) -> pd.DataFrame:
    d = d.copy()
    d["day"] = d.ts.dt.date
    d["hhmm"] = d.ts.dt.strftime("%H:%M")
    g = d.groupby("day").agg(o=("open", "first"), h=("high", "max"), l=("low", "min"), c=("close", "last"))
    h1 = d[d.hhmm < "10:15"].groupby("day").agg(h=("high", "max"), l=("low", "min"))
    f = pd.DataFrame(index=g.index)
    rng = g.h - g.l
    f["prev_range"] = rng.shift(1)
    f["avg5_range"] = rng.rolling(5).mean().shift(1)
    f["gap"] = (g.o / g.c.shift(1) - 1).abs() * 100
    f["hour1_range"] = h1.h - h1.l
    f["hindsight_oc"] = (g.c - g.o).abs()
    if vix is not None:
        f["vix"] = [vix[vix.index < day].iloc[-1] if (vix.index < day).any() else float("nan") for day in f.index]
    return f


def load_vix(path: str | None) -> pd.Series | None:
    if not path:
        return None
    r = json.load(open(path))["chart"]["result"][0]
    s = pd.Series(r["indicators"]["quote"][0]["close"],
                  index=pd.to_datetime(r["timestamp"], unit="s").tz_localize("UTC").tz_convert("Asia/Kolkata").date)
    return s.dropna().groupby(level=0).last()


def summarize(t: pd.DataFrame) -> dict:
    if t.empty:
        return dict(n=0, days=0, total=0.0, avg=0.0, win=0.0, big=0)
    return dict(n=len(t), days=t.day.nunique(), total=t.pts.sum(), avg=t.pts.mean(), win=(t.pts > 0).mean(),
                big=int((t.pts >= 100).sum()))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--recent")
    ap.add_argument("--vix")
    args = ap.parse_args()
    d = load(args.recent)
    t = trades(bars10(d))
    f = day_features(d, load_vix(args.vix))
    t = t.join(f, on="day")
    days = sorted(f.index)
    cut = days[int(len(days) * 2 / 3)]
    print(f"{len(days)} days {days[0]} .. {days[-1]}; train before {cut}, test from {cut}")
    filters = {
        "prev_range": (150, 200, 250, 300, 350),
        "avg5_range": (150, 200, 250, 300),
        "vix": (11, 12, 13, 14, 15, 16),
        "gap": (0.2, 0.3, 0.5, 0.8),
        "hour1_range": (80, 100, 120, 150, 200),
    }
    rows = []
    base_tr, base_te = summarize(t[t.day < cut]), summarize(t[t.day >= cut])
    rows.append(dict(filter="NO FILTER (base rule)", **{f"tr_{k}": v for k, v in base_tr.items()},
                     **{f"te_{k}": v for k, v in base_te.items()}))
    for col, levels in filters.items():
        if col not in t:
            continue
        for x in levels:
            sel = t[t[col] >= x]
            if col == "hour1_range":
                sel = sel[sel.entry_t >= "10:15"]
            tr, te = summarize(sel[sel.day < cut]), summarize(sel[sel.day >= cut])
            rows.append(dict(filter=f"{col} >= {x}", **{f"tr_{k}": v for k, v in tr.items()},
                             **{f"te_{k}": v for k, v in te.items()}))
    for x in (100, 150, 200):
        sel = t[t.hindsight_oc >= x]
        tr, te = summarize(sel[sel.day < cut]), summarize(sel[sel.day >= cut])
        rows.append(dict(filter=f"HINDSIGHT: day moved {x}+ open->close", **{f"tr_{k}": v for k, v in tr.items()},
                         **{f"te_{k}": v for k, v in te.items()}))
    r = pd.DataFrame(rows)
    pd.set_option("display.width", 220)
    for c in ("tr_total", "te_total", "tr_avg", "te_avg"):
        r[c] = r[c].round(0).astype(int)
    for c in ("tr_win", "te_win"):
        r[c] = (r[c] * 100).round(0).astype(int).astype(str) + "%"
    print(r[["filter", "tr_n", "tr_days", "tr_total", "tr_avg", "tr_win", "tr_big",
             "te_n", "te_days", "te_total", "te_avg", "te_win", "te_big"]].to_string(index=False))


if __name__ == "__main__":
    main()
