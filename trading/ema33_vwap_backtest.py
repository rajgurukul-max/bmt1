"""Intraday Nifty rule on 10-minute candles: 33-EMA channel break + VWAP + RSI.

  BULLISH  the 10-min candle CLOSES above the 33-EMA of the HIGHS (it just crossed: the
           previous candle closed at or below it), close above VWAP, RSI(14) >= 55
  BEARISH  closes below the 33-EMA of the LOWS (just crossed), close below VWAP, RSI(14) <= 45
  RSI between 45 and 55: no trade.   Intraday only: everything is closed by 15:10.

Entry = the signal candle's close, at most 2 trades a day, none before 09:45 or after 14:30.
You did not say how to exit, so several exits are compared (all keep a 60-point stop and
15:10): target 60 / 120, exit when a candle closes back inside the 33-EMA channel, a trailing
stop, or just the 15:10 close. Cost: 2 points per round trip for futures.

VWAP NOTE: the Nifty index has no volume, so a true VWAP does not exist for index candles.
Here VWAP = the day's running average of the typical price (high+low+close)/3, every candle
weighted equally. For the real VWAP the same test must be run on Nifty FUTURES candles.

Options: an ATM weekly option (call for a bullish trade, put for a bearish one) is priced with
Black-Scholes at entry and exit from the real Nifty path, India VIX (previous close) and the time
left to expiry, with 1.5 pts of slippage per fill. This is a MODEL, not real option prices.

Each calendar year is run on its own with prices rescaled so its median close is 25,000, so the
60-pt stop means the same % move in every year (results are in today-sized Nifty points).

Data: the 5-year file written by `ribbon_exit_test.py --multiyear` (else the 1-year file), topped
up with the latest days from Yahoo. Or --yahoo PATH for a quick 60-day check.
Usage on the VPS:  ~/venv/bin/python ema33_vwap_backtest.py
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta

import pandas as pd

import ribbon_exit_test as rx
import ribbon_filter_test as ft
import ribbon_trend_backtest as rb
import supertrend_spread_backtest as st

LOT, STOP, COST, SLIP, MAX_TRADES = 65, 60.0, 2.0, 1.5, 2
EXITS = {
    "stop 60 + 15:10 only": {},
    "stop 60 + target 60": {"target": 60},
    "stop 60 + target 120": {"target": 120},
    "stop 60 + exit when back inside channel": {"channel": True},
    "stop 60 + trail 150/80": {"trail": (150, 80)},
    "channel exit + trail 150/80": {"channel": True, "trail": (150, 80)},
}


def prep(d: pd.DataFrame) -> pd.DataFrame:
    b = rb.bars10(d, 10)
    b["ema_hi"] = b.high.ewm(span=33, adjust=False).mean()
    b["ema_lo"] = b.low.ewm(span=33, adjust=False).mean()
    tp = (b.high + b.low + b.close) / 3
    b["vwap"] = tp.groupby(b.day).transform(lambda x: x.expanding().mean())
    b["done"] = b.ts + pd.Timedelta(minutes=10)
    return b


def simulate(d: pd.DataFrame, b: pd.DataFrame, cfg: dict, use_vwap: bool = True, use_rsi: bool = True,
             sides: tuple = (1, -1)) -> pd.DataFrame:
    tenmin = b.set_index("done")
    out, pos, per_day, last, prev = [], None, {}, None, None

    def close(p, t, px, why):
        return dict(day=p["day"], entry_ts=p["ts"], exit_ts=t, side=p["side"], entry=p["entry"], exit=px,
                    pts=(px - p["entry"]) * p["side"] - COST, why=why)

    for r in d.itertuples(index=False):
        t, day, hhmm = r.ts, r.ts.date(), r.ts.strftime("%H:%M")
        if t in tenmin.index:
            prev, last = last, tenmin.loc[t]
            if pos and cfg.get("channel") and last.day == pos["day"] and (
                    (pos["side"] > 0 and last.close < last.ema_hi) or (pos["side"] < 0 and last.close > last.ema_lo)):
                out.append(close(pos, t, last.close, "channel"))
                pos = None
            if pos is None and prev is not None and last.day == day and "09:35" <= last.hhmm < "14:30" \
                    and per_day.get(day, 0) < MAX_TRADES and not pd.isna(prev.ema_hi):
                up = last.close > last.ema_hi and prev.close <= prev.ema_hi
                dn = last.close < last.ema_lo and prev.close >= prev.ema_lo
                if use_vwap:
                    up, dn = up and last.close > last.vwap, dn and last.close < last.vwap
                if use_rsi:
                    up, dn = up and last.rsi >= 55, dn and last.rsi <= 45
                side = 1 if up else -1 if dn else 0
                if side and side in sides:
                    pos = dict(side=side, entry=last.close, best=last.close, day=day, ts=t, stop=last.close - side * STOP)
                    per_day[day] = per_day.get(day, 0) + 1
        if pos is None:
            continue
        s = pos["side"]
        if hhmm >= "15:10":
            out.append(close(pos, t, r.open, "15:10"))
            pos = None
            continue
        levels = [pos["stop"]]
        if cfg.get("trail") and (pos["best"] - pos["entry"]) * s >= cfg["trail"][0]:
            levels.append(pos["best"] - s * cfg["trail"][1])
        lvl = max(levels, key=lambda x: x * s)
        if (s > 0 and r.low <= lvl) or (s < 0 and r.high >= lvl):
            px = min(r.open, lvl) if s > 0 else max(r.open, lvl)
            out.append(close(pos, t, px, "stop" if lvl == pos["stop"] else "trail"))
            pos = None
            continue
        if cfg.get("target"):
            tgt = pos["entry"] + s * cfg["target"]
            if (s > 0 and r.high >= tgt) or (s < 0 and r.low <= tgt):
                out.append(close(pos, t, max(r.open, tgt) if s > 0 else min(r.open, tgt), "target"))
                pos = None
                continue
        pos["best"] = max(pos["best"], r.high) if s > 0 else min(pos["best"], r.low)
    return pd.DataFrame(out, columns=["day", "entry_ts", "exit_ts", "side", "entry", "exit", "pts", "why"])


def weekly_expiry(day: date) -> date:
    wd = 1 if day >= date(2025, 9, 1) else 3                  # Tuesday since Sep 2025, Thursday before
    e = day + timedelta(days=1)
    while e.weekday() != wd:
        e += timedelta(days=1)
    return e


def option_pts(tr: pd.DataFrame, vix: pd.Series) -> pd.Series:
    """ATM weekly option P&L in points per trade (model prices), after slippage."""
    res = []
    for x in tr.itertuples():
        pv = vix[vix.index < x.entry_ts.date()]
        v0 = float(pv.iloc[-1]) / 100 if len(pv) else 0.15
        end = pd.Timestamp(weekly_expiry(x.entry_ts.date())) + pd.Timedelta(hours=15, minutes=30)
        k, call = round(x.entry / 50) * 50, x.side > 0
        t1 = (end - x.entry_ts).total_seconds() / (365 * 86400)
        t2 = (end - x.exit_ts).total_seconds() / (365 * 86400)
        res.append(max(st.bs(x.exit, k, t2, v0, call) - SLIP, 0) - (st.bs(x.entry, k, t1, v0, call) + SLIP))
    return pd.Series(res, index=tr.index, dtype=float)


def stats(t: pd.DataFrame, col: str = "pts") -> dict:
    if t.empty:
        return dict(n=0, total=0, win="-", avg=0.0, dd=0, worst=0)
    eq = t[col].cumsum()
    return dict(n=len(t), total=round(t[col].sum()), win=f"{(t[col] > 0).mean():.0%}", avg=round(t[col].mean(), 1),
                dd=round((eq.cummax() - eq).max()), worst=round(t[col].min()))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yahoo", help="Yahoo chart JSON only (60 days, quick check)")
    args = ap.parse_args()
    if args.yahoo:
        d = ft.normalize(ft.load_yahoo(args.yahoo))
    else:
        path = rx.MULTI_CACHE if rx.MULTI_CACHE.exists() else ft.CACHE
        d = ft.normalize(pd.read_csv(path))
        y = rx.yahoo_recent()
        if y is not None:
            y = ft.normalize(y)
            d = pd.concat([d, y[y.ts > d.ts.max()]], ignore_index=True)
    v = st.yahoo_daily("%5EINDIAVIX", "indiavix")
    vix = pd.Series(v.c.values, index=v.date.values)
    parts = []
    for yr in sorted(set(d.ts.dt.year)):
        part = d[(d.ts >= pd.Timestamp(yr, 1, 1) - pd.Timedelta(days=40)) & (d.ts < pd.Timestamp(yr + 1, 1, 1))].copy()
        inyr = part[part.ts.dt.year == yr]
        if inyr.ts.dt.date.nunique() < 40:
            continue
        part[["open", "high", "low", "close"]] *= 25000 / inyr.close.median()
        parts.append((yr, part, prep(part), inyr.ts.dt.date.nunique()))
    days = sum(p[3] for p in parts)
    print(f"{d.ts.dt.date.min()} .. {d.ts.dt.date.max()}, {days} trading days, {len(parts)} calendar year(s); "
          f"points are today-sized (Nifty ~25,000); 1 lot = {LOT}; VWAP = running average (index has no volume).")

    def run(cfg, **kw):
        trs = []
        for yr, part, b, _ in parts:
            t = simulate(part, b, cfg, **kw)
            t = t[pd.to_datetime(t.day).dt.year == yr].copy()
            t["opt"] = option_pts(t, vix) if len(t) else []
            t["yr"] = yr
            trs.append(t)
        return pd.concat(trs, ignore_index=True)

    def table(variants):
        rows = []
        for name, t in variants:
            f, o = stats(t), stats(t, "opt")
            r = {"version": name}
            for yr, *_ in parts:
                x = t[t.yr == yr]
                r[str(yr)] = f"{x.pts.sum():+.0f} ({(x.pts > 0).mean():.0%})" if len(x) else "-"
            r.update({"FUT total": f["total"], "trades": f["n"], "win": f["win"], "avg": f["avg"], "max_dd": f["dd"],
                      "worst": f["worst"], "FUT Rs/lot/yr": round(f["total"] * LOT / (days / 250)),
                      "OPT total": o["total"], "OPT win": o["win"], "OPT Rs/lot/yr": round(o["total"] * LOT / (days / 250))})
            rows.append(r)
        pd.set_option("display.width", 300)
        pd.set_option("display.max_columns", 30)
        print(pd.DataFrame(rows).to_string(index=False))

    print("\n=== YOUR RULE, with different exits (FUT = futures points; OPT = modelled ATM weekly option points) ===")
    base = {name: run(cfg) for name, cfg in EXITS.items()}
    table(list(base.items()))
    pick = "stop 60 + exit when back inside channel"
    print(f"\n=== What each condition adds (exit: {pick}) ===")
    cfg = EXITS[pick]
    table([("rule as given", base[pick]),
           ("without the VWAP filter", run(cfg, use_vwap=False)),
           ("without the RSI filter", run(cfg, use_rsi=False)),
           ("neither (pure channel break)", run(cfg, use_vwap=False, use_rsi=False)),
           ("bullish trades only", run(cfg, sides=(1,))),
           ("bearish trades only", run(cfg, sides=(-1,)))])
    t = base[pick]
    print(f"\nHow the trades ended ({pick}): " + ", ".join(f"{k} {v}" for k, v in t.why.value_counts().items()))


if __name__ == "__main__":
    main()
