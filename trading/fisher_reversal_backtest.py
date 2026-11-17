"""Pure Ehlers Fisher Transform stop-and-reverse on the Nifty (futures points). No other indicator.

  Fisher crosses ABOVE its trigger line (the Fisher value one candle earlier) -> go long (and close any short)
  Fisher crosses BELOW the trigger                                              -> go short (and close any long)
  Always in the market after the first signal; no stop-loss, no target. The crossover is seen on the
  candle's close and traded at that close. Fisher length 9 (the TradingView default) unless stated.

Variants: LONG ONLY (a bearish cross just closes the long, no shorting), SHORT ONLY, and BOTH (reverse).
Two ways to run it:
  INTRADAY   flat by ~15:10 every day, a fresh start next morning (only crossovers inside the day count)
  OVERNIGHT  the position is carried overnight and flips only on the next crossover
Timeframes: 5 / 10 / 15 / 30 / 60-minute candles and DAILY candles (daily is overnight only).

Because it flips so often the cost per trade decides everything, so each result is shown GROSS (no cost)
and NET of 2 points (what the other backtests use) and 8 points (a realistic Nifty futures cost: STT,
brokerage, exchange fees and slippage). Points are Nifty-at-25,000 points: each calendar year is rescaled
so its median close is 25,000.

Data: the 5-year 5-minute file written by `ribbon_exit_test.py --multiyear` (daily: Yahoo, 10 years).
Usage on the VPS:  ~/venv/bin/python fisher_reversal_backtest.py          (--yahoo = 60-day check, no files)
"""
from __future__ import annotations

import argparse

import pandas as pd

import ribbon_exit_test as rx
import ribbon_filter_test as ft
import ribbon_trend_backtest as rb
import supertrend_spread_backtest as st

COSTS = (0, 2, 8)


def candles(d: pd.DataFrame, tf: int) -> pd.DataFrame:
    b = d.set_index("ts").resample(f"{tf}min", origin="start_day", offset="15min").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna().reset_index()
    b["day"], b["hhmm"], b["tf"] = b.ts.dt.date, b.ts.dt.strftime("%H:%M"), tf
    return b


def add_fisher(b: pd.DataFrame, n: int) -> pd.DataFrame:
    f, trig = rb.fisher(b.high, b.low, n)
    above = f > trig
    was = above.shift(1, fill_value=False)
    b["fish_x"] = (above & ~was).astype(int) - (~above & was & trig.notna()).astype(int)   # +1 up-cross, -1 down-cross
    return b


def reverse_trades(b: pd.DataFrame, intraday: bool, year: int, sides: tuple = (1, -1)) -> pd.DataFrame:
    """Stop-and-reverse trades inside one calendar year. Gross points per trade (no cost).
    sides=(1,): LONG ONLY -- a bearish cross closes the long and the system stays flat until the next bullish
    cross; sides=(-1,): SHORT ONLY, the mirror image."""
    rows = b[b.ts.dt.year == year].reset_index(drop=True)
    flat_at = {}
    if intraday:                                  # the last candle that ends by 15:15: flatten there, no signals after it
        ok = rows[(rows.hhmm < "15:10") & (rows.ts + pd.to_timedelta(rows.tf, unit="min")
                                           <= rows.ts.dt.normalize() + pd.Timedelta(hours=15, minutes=15))]
        flat_at = {r.day: i for i, r in ok.groupby("day").tail(1).iterrows()}
    flat = set(flat_at.values())
    out, pos, entry, ent_ts = [], 0, 0.0, None
    for i, r in enumerate(rows.itertuples(index=False)):
        late = intraday and i >= flat_at.get(r.day, 10 ** 9)
        if r.fish_x != 0 and not late and pos != r.fish_x:
            if pos:
                out.append((ent_ts, r.ts, pos, (r.close - entry) * pos))
            pos, entry, ent_ts = (int(r.fish_x), r.close, r.ts) if r.fish_x in sides else (0, 0.0, None)
        if pos and ((intraday and i in flat) or i == len(rows) - 1):
            out.append((ent_ts, r.ts, pos, (r.close - entry) * pos))
            pos = 0
    return pd.DataFrame(out, columns=["entry_ts", "exit_ts", "side", "gross"])


def run(d: pd.DataFrame, tf: int, n: int, intraday: bool, sides: tuple = (1, -1)) -> pd.DataFrame:
    trs = []
    for yr in sorted(set(d.ts.dt.year)):
        part = d[(d.ts >= pd.Timestamp(yr, 1, 1) - pd.Timedelta(days=60)) & (d.ts < pd.Timestamp(yr + 1, 1, 1))].copy()
        inyr = part[part.ts.dt.year == yr]
        if inyr.ts.dt.date.nunique() < 40:
            continue
        part[["open", "high", "low", "close"]] *= 25000 / inyr.close.median()
        t = reverse_trades(add_fisher(candles(part, tf), n), intraday, yr, sides)
        t["yr"] = yr
        trs.append(t)
    return pd.concat(trs, ignore_index=True) if trs else pd.DataFrame(columns=["entry_ts", "exit_ts", "side", "gross", "yr"])


def summarize(name: str, t: pd.DataFrame, years: float) -> dict:
    if t.empty:
        return {"setup": name}
    net2 = t.gross - 2
    eq = net2.cumsum()
    yrs = (t.gross - 2).groupby(t.yr).sum()
    return {"setup": name, "trades": len(t), "per_yr": round(len(t) / years), "avg_gross": round(t.gross.mean(), 1),
            "win_gross": f"{(t.gross > 0).mean():.0%}", "GROSS": round(t.gross.sum()), "NET@2": round(net2.sum()),
            "NET@8": round((t.gross - 8).sum()), "yrs+(net2)": f"{int((yrs > 0).sum())}/{len(yrs)}",
            "max_dd(net2)": round((eq.cummax() - eq).max()),
            "long_avg": round(t[t.side > 0].gross.mean(), 1), "short_avg": round(t[t.side < 0].gross.mean(), 1)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yahoo", action="store_true", help="quick check: last 60 days of 5-minute data from Yahoo")
    args = ap.parse_args()
    if args.yahoo:
        d = ft.normalize(rx.yahoo_recent())
    else:
        d = ft.normalize(pd.read_csv(rx.MULTI_CACHE if rx.MULTI_CACHE.exists() else ft.CACHE))
        y = rx.yahoo_recent()
        if y is not None:
            y = ft.normalize(y)
            d = pd.concat([d, y[y.ts > d.ts.max()]], ignore_index=True)
    days = d.ts.dt.date.nunique()
    years = max(days / 250, 0.1)
    print(f"{d.ts.dt.date.min()} .. {d.ts.dt.date.max()}, {days} trading days ({years:.1f} years). "
          f"Points: Nifty-at-25,000. Fisher length 9 unless stated.")
    SIDES = {"LONG ONLY": (1,), "SHORT ONLY": (-1,), "BOTH (reverse)": (1, -1)}
    dly = None
    if not args.yahoo:
        dd = st.yahoo_daily("%5ENSEI", "nifty")
        dly = pd.DataFrame({"ts": pd.to_datetime(dd.date), "open": dd.o, "high": dd.h, "low": dd.l, "close": dd.c})
        dly["hhmm"] = "00:00"

    def daily(sides):
        t = []
        for yr in sorted(set(dly.ts.dt.year)):
            part = dly[(dly.ts >= pd.Timestamp(yr, 1, 1) - pd.Timedelta(days=200)) & (dly.ts < pd.Timestamp(yr + 1, 1, 1))].copy()
            inyr = part[part.ts.dt.year == yr]
            part[["open", "high", "low", "close"]] *= 25000 / inyr.close.median()
            x = reverse_trades(add_fisher(part.assign(day=part.ts.dt.date, tf=1440), 9), False, yr, sides)
            x["yr"] = yr
            t.append(x)
        return pd.concat(t, ignore_index=True)

    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    for label, sides in SIDES.items():
        rows = []
        for tf in (5, 10, 15, 30, 60):
            for intraday in (True, False):
                rows.append(summarize(f"{tf}-min, {'INTRADAY' if intraday else 'OVERNIGHT'}", run(d, tf, 9, intraday, sides), years))
        if dly is not None:
            rows.append(summarize("DAILY candles, 10 years", daily(sides), dly.ts.dt.year.nunique()))
        print(f"\n=== {label}: Fisher length 9, by timeframe (GROSS = before costs; NET@2 / NET@8 = after 2 / 8 pts per trade) ===")
        print(pd.DataFrame(rows).to_string(index=False))
    rows = []
    for label, sides in SIDES.items():
        for n in (9, 13, 21):
            for intraday in (True, False):
                rows.append(summarize(f"{label}, 10-min, length {n}, {'INTRADAY' if intraday else 'OVERNIGHT'}",
                                      run(d, 10, n, intraday, sides), years))
    print("\n=== Fisher length (10-minute candles) ===")
    print(pd.DataFrame(rows).to_string(index=False))
    for label, sides in (("LONG ONLY", (1,)), ("SHORT ONLY", (-1,))):
        t = run(d, 10, 9, False, sides)
        yr = t.groupby("yr").agg(trades=("gross", "size"), gross=("gross", "sum"))
        yr["net@2"], yr["net@8"] = yr.gross - 2 * yr.trades, yr.gross - 8 * yr.trades
        print(f"\n{label}, 10-min OVERNIGHT, year by year (points):\n" + yr.round(0).to_string())


if __name__ == "__main__":
    main()
