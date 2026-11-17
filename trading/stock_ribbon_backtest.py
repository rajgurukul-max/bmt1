"""The live Nifty ribbon rule tested on liquid F&O STOCKS (traded as stock futures).

Rule = exactly what nifty_ribbon_signals.py trades: 10-min candles, EMA9/21/50 stack, RSI 60/40,
MACD histogram rising/falling, trending/quiet day switch, max 2 trades a day, no repeat in a
direction after a stop-loss, 60-pt stop, exit 20 pts through EMA21, trailing stop 150/80, 15:10.

Those point settings are tuned to the Nifty (~25,000, daily range ~215 pts), so every stock is
rescaled: its prices are multiplied so that its MEDIAN DAILY RANGE equals 215 points. The stop is
then ~0.28 x the stock's normal daily range, the same as on the Nifty. Each calendar year is scaled
on its own. Results are shown as a % of the stock's price.

Costs: a round-trip % of price (default 0.05% for stock futures: STT 0.02%, brokerage/exchange/stamp
~0.01%, slippage ~0.02%; the Nifty future is ~0.032%). Options are NOT tested: single-stock option
spreads are wide and there is no implied-vol history to price them with.

Data:  --download   fetch 5 years of 5-minute candles for the stock list from Kite (needs today's login;
                    read-only; saved in data_cache/stocks/, resumable)
       --yahoo      quick check on the last 60 days from Yahoo (no login)
       (default)    use the downloaded files
Usage on the VPS:  ~/venv/bin/python stock_ribbon_backtest.py --download
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime, timedelta

import pandas as pd

import ribbon_exit_test as rx
import ribbon_filter_test as ft
from config import BASE_DIR

CACHE_DIR = BASE_DIR / "data_cache" / "stocks"
REF_RANGE = 215.0                     # Nifty's median daily range in "25,000-level" points
NIFTY_COST_PCT = 0.032
UNIVERSE = ["RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS", "SBIN", "AXISBANK", "KOTAKBANK", "LT", "ITC",
            "BHARTIARTL", "BAJFINANCE", "MARUTI", "HINDUNILVR", "SUNPHARMA", "TITAN", "NTPC", "TATASTEEL",
            "M&M", "ASIANPAINT"]
LIVE = dict(exit_mode="touch", touch_buf=20, trail=(150, 80))      # the live intraday rule


def yahoo_ticker(sym: str) -> str:
    return {"NIFTY": "%5ENSEI"}.get(sym, sym.replace("&", "%26") + ".NS")


def yahoo_5m(sym: str) -> pd.DataFrame | None:
    try:
        import requests
        r = requests.get(f"https://query2.finance.yahoo.com/v8/finance/chart/{yahoo_ticker(sym)}?range=60d&interval=5m",
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=30).json()["chart"]["result"][0]
        q = r["indicators"]["quote"][0]
        d = pd.DataFrame({"ts": pd.to_datetime(r["timestamp"], unit="s", utc=True), "open": q["open"],
                          "high": q["high"], "low": q["low"], "close": q["close"]})
        return ft.normalize(d)
    except Exception as exc:
        print(f"  (Yahoo failed for {sym}: {exc})")
        return None


def download_all(syms: list[str], years: int) -> None:
    from dotenv import load_dotenv

    from config import load_config
    from data import get_kite_client
    load_dotenv(BASE_DIR / ".env", override=True)
    kite = get_kite_client(load_config())
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    end = datetime.now()
    for sym in syms:
        path = CACHE_DIR / f"{sym.replace('&', '_')}_5minute.csv"
        if path.exists():
            print(f"{sym}: already downloaded")
            continue
        token = kite.ltp([f"NSE:{sym}"])[f"NSE:{sym}"]["instrument_token"]      # also fails fast on a stale login
        start, rows = end - timedelta(days=int(years * 365.25) + 40), []
        while start < end:
            stop = min(start + timedelta(days=90), end)
            rows += kite.historical_data(token, start, stop, "5minute")
            start = stop
            time.sleep(0.4)
        pd.DataFrame(rows).drop_duplicates("date").to_csv(path, index=False)
        print(f"{sym}: saved {len(rows)} candles")


def load_cached(sym: str) -> pd.DataFrame | None:
    if sym == "NIFTY":
        path = rx.MULTI_CACHE
    else:
        path = CACHE_DIR / f"{sym.replace('&', '_')}_5minute.csv"
    return ft.normalize(pd.read_csv(path)) if path.exists() else None


def run_symbol(d: pd.DataFrame, cost_pct: float) -> tuple[pd.DataFrame, float]:
    """Trades of the live rule on one symbol, year by year; pct = result as % of price."""
    out, adr_pct = [], []
    for yr in sorted(set(d.ts.dt.year)):
        part = d[(d.ts >= pd.Timestamp(yr, 1, 1) - pd.Timedelta(days=40)) & (d.ts < pd.Timestamp(yr + 1, 1, 1))].copy()
        inyr = part[part.ts.dt.year == yr]
        if inyr.ts.dt.date.nunique() < 40:
            continue
        day = inyr.groupby(inyr.ts.dt.date).agg(h=("high", "max"), l=("low", "min"), c=("close", "last"))
        rng = float((day.h - day.l).median())
        f = REF_RANGE / rng
        px = float(inyr.close.median()) * f                                  # scaled price level
        adr_pct.append(rng / float(inyr.close.median()) * 100)
        part[["open", "high", "low", "close"]] *= f
        rx.COST = cost_pct / 100 * px                                        # cost in scaled points
        t = rx.simulate(part, **LIVE)
        t = t[pd.to_datetime(t.day).dt.year == yr].copy()
        t["pct"] = t.pts / px * 100
        t["yr"] = yr
        out.append(t)
    t = pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=["day", "side", "pts", "pct", "yr"])
    return t, (sum(adr_pct) / len(adr_pct) if adr_pct else 0.0)


def dd(x: pd.Series) -> float:
    eq = x.cumsum()
    return float((eq.cummax() - eq).max()) if len(eq) else 0.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", action="store_true", help="fetch the stocks' 5-minute history from Kite first")
    ap.add_argument("--years", type=int, default=5)
    ap.add_argument("--yahoo", action="store_true", help="quick check: last 60 days from Yahoo, no login")
    ap.add_argument("--cost-pct", type=float, default=0.05, help="round-trip cost of a stock future, %% of price")
    ap.add_argument("--stocks", help="comma-separated subset of the stock list")
    args = ap.parse_args()
    syms = args.stocks.split(",") if args.stocks else UNIVERSE
    if args.download:
        download_all(syms, args.years)
    rows, alltr = [], []
    for sym in ["NIFTY"] + syms:
        d = yahoo_5m(sym) if args.yahoo else load_cached(sym)
        if d is None or d.empty:
            print(f"{sym}: no data, skipped")
            continue
        t, adr = run_symbol(d, NIFTY_COST_PCT if sym == "NIFTY" else args.cost_pct)
        if t.empty:
            continue
        t["sym"] = sym
        if sym != "NIFTY":
            alltr.append(t)
        yrs = t.groupby("yr").pct.sum()
        rows.append({"symbol": sym, "range%/day": round(adr, 2), "trades": len(t), "win": f"{(t.pct > 0).mean():.0%}",
                     "avg%/trade": round(t.pct.mean(), 3), "total%": round(t.pct.sum(), 1),
                     "max_dd%": round(dd(t.pct), 1), "yrs_pos": f"{int((yrs > 0).sum())}/{len(yrs)}"})
        print(f"  {sym} done", flush=True)
    pd.set_option("display.width", 200)
    print(f"\nLive ribbon rule per symbol (rescaled to Nifty-size moves; stock cost {args.cost_pct}% round trip, "
          f"Nifty {NIFTY_COST_PCT}%). Results in % of price.")
    print(pd.DataFrame(rows).to_string(index=False))
    if not alltr:
        return
    a = pd.concat(alltr, ignore_index=True)
    print(f"\n=== ALL {a.sym.nunique()} STOCKS POOLED (1 unit per trade) ===")
    yr = a.groupby("yr").agg(trades=("pct", "size"), win=("pct", lambda x: f"{(x > 0).mean():.0%}"),
                             avg_pct=("pct", "mean"), total_pct=("pct", "sum")).round(3)
    print(yr.to_string())
    daily = a.groupby("day").pct.sum()
    nstk = a.groupby("day").sym.nunique()
    print(f"\nPooled: {len(a)} trades, win {(a.pct > 0).mean():.0%}, avg {a.pct.mean():.3f}% per trade, total {a.pct.sum():.0f}%, "
          f"max drawdown {dd(daily.sort_index()):.0f}%, worst day {daily.min():.1f}%, "
          f"on trading days with a trade the average is {nstk.mean():.1f} stocks, the busiest day {nstk.max()}.")
    side = a.groupby("side").agg(trades=("pct", "size"), avg_pct=("pct", "mean"), total_pct=("pct", "sum")).round(3)
    side.index = side.index.map({1: "bullish", -1: "bearish"})
    print("\nBy direction:\n" + side.to_string())
    s = a.groupby("sym").pct.sum().sort_values()
    print(f"\nStocks with a positive total: {int((s > 0).sum())} of {len(s)}. Worst: " +
          ", ".join(f"{k} {v:+.1f}" for k, v in s.head(3).items()) + " | best: " +
          ", ".join(f"{k} {v:+.1f}" for k, v in s.tail(3)[::-1].items()))


if __name__ == "__main__":
    main()
