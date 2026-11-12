"""Positional Nifty debit spreads driven by the DAILY Supertrend -- backtest only.

Signal (daily candles): Supertrend(10, 3); a flip is acted on at the next
day's open. Three ways to hold the trend are compared:
  FUTURES  one Nifty future (no cap on profit or loss)
  BUY      a debit spread in the trend's direction: uptrend -> buy the ATM call,
           sell the call WIDTH higher (downtrend -> the put spread). Max loss =
           the debit paid.
  SELL     a credit spread against the other side: uptrend -> sell a put OTM%
           below spot and buy the put WIDTH lower (downtrend -> a call spread
           above). Max loss = width - credit.
Widths and distances are a % of spot, so they mean the same in 2017 and 2026.
Monthly expiry at least MIN_DTE days out, rolled when ROLL_DTE days are left
(optionally also once 80% of the possible profit is made).

There is no historical option data here, so prices are MODELLED: Black-Scholes
on the real daily Nifty path with India VIX as implied volatility and a simple
skew (lower strikes cost more vol). Costs: 1.5 pts per leg per fill plus ~1 pt
of charges per spread per side. Treat the rupee results as estimates.

Data: Yahoo daily ^NSEI and ^INDIAVIX (10 years), cached in data_cache/.

Usage: python supertrend_spread_backtest.py [--atr 10 --mult 3] [--lot 65]
"""
from __future__ import annotations

import argparse
import calendar
import json
import math
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

CACHE = Path(__file__).resolve().parent / "data_cache"
RATE = 0.065
SKEW = 0.004            # +0.4 vol points per 1% the strike is below spot (minus above)
LEG_SLIP, SIDE_CHARGES = 1.5, 1.0
MIN_DTE, ROLL_DTE = 20, 5
RECENTRE_AT = 0.80      # re-centre once the spread is worth 80% of its width


def yahoo_daily(symbol: str, name: str) -> pd.DataFrame:
    path = CACHE / f"daily_{name}.csv"
    try:
        import requests
        r = requests.get(f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}?range=10y&interval=1d",
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=30).json()["chart"]["result"][0]
        q = r["indicators"]["quote"][0]
        d = pd.DataFrame({"date": pd.to_datetime(r["timestamp"], unit="s", utc=True).tz_convert("Asia/Kolkata").date,
                          "o": q["open"], "h": q["high"], "l": q["low"], "c": q["close"]}).dropna()
        CACHE.mkdir(exist_ok=True)
        d.to_csv(path, index=False)
    except Exception as exc:
        print(f"(download of {symbol} failed: {exc} -- using {path.name})")
        d = pd.read_csv(path, parse_dates=["date"])
        d["date"] = d["date"].dt.date
    return d.drop_duplicates("date").reset_index(drop=True)


def supertrend(d: pd.DataFrame, n: int, mult: float) -> pd.Series:
    """+1 while the daily Supertrend is up, -1 while it is down."""
    tr = pd.concat([d.h - d.l, (d.h - d.c.shift()).abs(), (d.l - d.c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / n, adjust=False).mean()
    mid = (d.h + d.l) / 2
    ub, lb = (mid + mult * atr).tolist(), (mid - mult * atr).tolist()
    c, out = d.c.tolist(), [1]
    for i in range(1, len(d)):
        if not (ub[i] < ub[i - 1] or c[i - 1] > ub[i - 1]):
            ub[i] = ub[i - 1]
        if not (lb[i] > lb[i - 1] or c[i - 1] < lb[i - 1]):
            lb[i] = lb[i - 1]
        out.append(1 if c[i] > ub[i - 1] else -1 if c[i] < lb[i - 1] else out[-1])
    return pd.Series(out, index=d.index)


def monthly_expiry(y: int, m: int) -> date:
    """Last Thursday of the month; last Tuesday from September 2025 (NSE's change)."""
    wd = 1 if (y, m) >= (2025, 9) else 3
    last = date(y, m, calendar.monthrange(y, m)[1])
    return last - timedelta(days=(last.weekday() - wd) % 7)


def pick_expiry(today: date, min_dte: int) -> date:
    y, m = today.year, today.month
    while True:
        e = monthly_expiry(y, m)
        if (e - today).days >= min_dte:
            return e
        y, m = (y, m + 1) if m < 12 else (y + 1, 1)


def bs(s: float, k: float, t: float, vol: float, call: bool) -> float:
    if t <= 0:
        return max(s - k, 0.0) if call else max(k - s, 0.0)
    d1 = (math.log(s / k) + (RATE + vol * vol / 2) * t) / (vol * math.sqrt(t))
    d2 = d1 - vol * math.sqrt(t)
    n = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))
    return s * n(d1) - k * math.exp(-RATE * t) * n(d2) if call else k * math.exp(-RATE * t) * n(-d2) - s * n(-d1)


def mark(p: dict, s: float, vix: float, today: date) -> float:
    """What the spread is worth now: bought leg minus sold leg (negative for a credit spread)."""
    t = max((p["expiry"] - today).days, 0) / 365
    iv = lambda k: max(vix / 100 + SKEW * (1 - k / s) * 100, 0.05)
    return bs(s, p["k_buy"], t, iv(p["k_buy"]), p["call"]) - bs(s, p["k_sell"], t, iv(p["k_sell"]), p["call"])


def run(d: pd.DataFrame, trend: pd.Series, style: str, width_pct: float, both: bool,
        otm_pct: float = 0.0, recentre: bool = False) -> tuple[pd.DataFrame, pd.Series]:
    """style 'debit':  trend up -> BUY a call spread (ATM / ATM+width), down -> BUY a put spread.
       style 'credit': trend up -> SELL a put spread (short strike otm_pct below spot, protection
                       `width` lower), down -> SELL a call spread above spot.
       P&L = change in the spread's mark, minus costs. Max loss: the debit paid, or width - credit."""
    side_cost = 2 * LEG_SLIP + SIDE_CHARGES
    pos, seg, segs, realised, equity = None, None, [], 0.0, []

    def open_(side: int, s: float, vix: float, today: date) -> dict:
        w = max(round(s * width_pct / 100 / 50) * 50, 50)
        if style == "debit":
            k_buy = round(s / 50) * 50
            p = dict(call=side > 0, k_buy=k_buy, k_sell=k_buy + side * w)
        else:
            k_sell = round(s * (1 - side * otm_pct / 100) / 50) * 50
            p = dict(call=side < 0, k_sell=k_sell, k_buy=k_sell - side * w)
        p.update(side=side, expiry=pick_expiry(today, MIN_DTE), width=w)
        p["entry"] = mark(p, s, vix, today)
        p["risk"] = (p["entry"] if style == "debit" else w + p["entry"]) + 2 * side_cost
        return p

    def close_(s: float, vix: float, today: date) -> float:
        return mark(pos, s, vix, today) - pos["entry"] - 2 * side_cost

    def done(p: dict, s: float, vix: float, today: date) -> bool:
        """80% of the possible profit is already made."""
        m = mark(p, s, vix, today)
        return m >= RECENTRE_AT * p["width"] if style == "debit" else m >= (1 - RECENTRE_AT) * p["entry"]

    for i in range(1, len(d)):
        today, s, vix = d.date[i], d.o[i], d.vix[i - 1]
        want = trend[i - 1] if both or trend[i - 1] > 0 else 0
        if pos and want != pos["side"]:                         # trend flipped: close the spread
            pnl = close_(s, vix, today)
            realised += pnl
            seg["pts"] += pnl
            segs.append({**seg, "out": today})
            pos = seg = None
        if pos and ((pos["expiry"] - today).days <= ROLL_DTE or (recentre and done(pos, s, vix, today))):
            pnl = close_(s, vix, today)                         # roll to the next month / re-centre on spot
            realised += pnl
            seg["pts"] += pnl
            seg["rolls"] += 1
            pos = open_(pos["side"], s, vix, today)
            seg["risk"] = max(seg["risk"], pos["risk"])
        if not pos and want:
            pos = open_(want, s, vix, today)
            seg = {"in": today, "side": want, "pts": 0.0, "rolls": 0, "risk": pos["risk"]}
        equity.append(realised + (mark(pos, d.c[i], d.vix[i], today) - pos["entry"] - side_cost if pos else 0.0))
    if pos:                                                     # still open: marked at the last close
        segs.append({**seg, "pts": seg["pts"] + mark(pos, d.c.iloc[-1], d.vix.iloc[-1], d.date.iloc[-1])
                     - pos["entry"] - side_cost, "out": None})
    return pd.DataFrame(segs), pd.Series(equity, index=d.date[1:])


def futures(d: pd.DataFrame, trend: pd.Series, both: bool) -> tuple[pd.DataFrame, pd.Series]:
    """The same signals with one Nifty future (no cap on profit or loss), 5 pts cost per trade."""
    pos, entry, start, realised, segs, equity = 0, 0.0, None, 0.0, [], []
    for i in range(1, len(d)):
        want = trend[i - 1] if both or trend[i - 1] > 0 else 0
        if want != pos:
            if pos:
                pnl = (d.o[i] - entry) * pos - 5
                realised += pnl
                segs.append({"in": start, "side": pos, "pts": pnl, "rolls": 0, "risk": float("nan"), "out": d.date[i]})
            pos, entry, start = want, d.o[i], d.date[i]
        equity.append(realised + ((d.c[i] - entry) * pos if pos else 0.0))
    if pos:
        segs.append({"in": start, "side": pos, "pts": (d.c.iloc[-1] - entry) * pos, "rolls": 0, "risk": float("nan"),
                     "out": None})
    return pd.DataFrame(segs), pd.Series(equity, index=d.date[1:])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--atr", type=int, default=10)
    ap.add_argument("--mult", type=float, default=3.0)
    ap.add_argument("--lot", type=int, default=65, help="Nifty lot size for the rupee columns")
    args = ap.parse_args()
    d = yahoo_daily("%5ENSEI", "nifty")
    v = yahoo_daily("%5EINDIAVIX", "indiavix")
    d = d.merge(v[["date", "c"]].rename(columns={"c": "vix"}), on="date", how="left")
    d["vix"] = d.vix.ffill().bfill()
    trend = supertrend(d, args.atr, args.mult)
    years = (d.date.iloc[-1] - d.date.iloc[0]).days / 365
    print(f"Nifty daily {d.date.iloc[0]} .. {d.date.iloc[-1]} ({years:.1f} years), Supertrend({args.atr}, {args.mult:g}); "
          f"up {int((trend > 0).mean() * 100)}% of days. Rupees are per 1 lot of {args.lot}.")
    runs = [("FUTURES, uptrends only", futures(d, trend, False)), ("FUTURES, up + down", futures(d, trend, True))]
    runs += [(f"BUY call spread {w}% wide (uptrends)", run(d, trend, "debit", w, False)) for w in (2, 4)]
    runs += [("BUY call/put spread 2% wide (up + down)", run(d, trend, "debit", 2, True))]
    runs += [("BUY plain ATM call (uptrends)", run(d, trend, "debit", 60, False))]
    runs += [(f"SELL put spread {o}% below, {w}% wide (uptrends)", run(d, trend, "credit", w, False, o))
             for o, w in ((0, 2), (1, 2), (2, 2), (1, 3), (2, 3))]
    runs += [("SELL put spread 1% below, 2% wide, re-centre", run(d, trend, "credit", 2, False, 1, True))]
    runs += [("SELL put/call spread 1% away, 2% wide (up + down)", run(d, trend, "credit", 2, True, 1))]
    rows, keep = [], {}
    for name, (t, eq) in runs:
        last = eq.groupby(pd.to_datetime(eq.index).year).last()
        yr = last.diff().fillna(last)
        keep[name] = (t, yr)
        rows.append({"version": name, "trends": len(t), "win": f"{(t.pts > 0).mean():.0%}",
                     "total_pts": round(eq.iloc[-1]), "Rs/lot/yr": round(eq.iloc[-1] * args.lot / years),
                     "avg_risk_Rs": "-" if t.risk.isna().all() else round(t.risk.mean() * args.lot),
                     "worst_trend_Rs": round(t.pts.min() * args.lot), "best_trend_Rs": round(t.pts.max() * args.lot),
                     "max_dd_Rs": round((eq.cummax() - eq).max() * args.lot),
                     "losing_yrs": f"{int((yr < 0).sum())}/{len(yr)}",
                     "last_12m_Rs": round((eq.iloc[-1] - eq.iloc[-250]) * args.lot)})
    pd.set_option("display.width", 250)
    print(pd.DataFrame(rows).to_string(index=False))
    for name in ("FUTURES, uptrends only", "SELL put spread 1% below, 2% wide (uptrends)"):
        t, yr = keep[name]
        print(f"\n{name} -- per year (Rs per lot): " + ", ".join(f"{y}: {round(p * args.lot):+,}" for y, p in yr.items()))
        print(t.tail(4).assign(pts=t.pts.round(0), risk=t.risk.round(0)).to_string(index=False))


if __name__ == "__main__":
    main()
