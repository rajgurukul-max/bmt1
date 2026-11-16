"""Faster exits for the live Nifty ribbon rule, tested over the last year.

Entries are exactly the live rule (RSI 60/40, market-type switch, max 2 a day,
no same-direction signal after a stop-loss). Exits are checked on 5-minute
candles (finer than the 10-min signal candles, so a fast reversal is seen the
way the live script sees it):
  close    TODAY'S RULE: a 10-min candle CLOSES back through EMA21
  touch+N  price trades N pts beyond EMA21 (EMA21 of the last finished 10-min
           candle), no need to wait for the close; N = 0/10/20
  trail X/Y once the trade is X pts in profit, exit if price comes back Y pts
           from its best (on top of the 'close' rule)
  be X     once X pts in profit, the stop moves to the entry price
Every version keeps the 60-pt stop and the 15:10 exit; 2 pts cost per trade.

Data: data_cache/NIFTY50_5minute_1y.csv (saved by ribbon_filter_test.py
--download), extended with the last days from Yahoo (no login needed).

Usage on the VPS:  ~/venv/bin/python ribbon_exit_test.py
                   ~/venv/bin/python ribbon_exit_test.py --reentry   (re-entry rules, live exit)
                   ~/venv/bin/python ribbon_exit_test.py --entry     (MACD vs Fisher Transform entry)
                   ~/venv/bin/python ribbon_exit_test.py --explore   (earlier entry / other exits / 5-min)
                   ~/venv/bin/python ribbon_exit_test.py --swing     (carry overnight, no 15:10 exit)
Many years (first time needs the morning login):  ... ribbon_exit_test.py --multiyear
Sensex (first time, after the morning login):  ... ribbon_exit_test.py --index sensex --download --swing
       (later runs: drop --download; add --explore / --entry / --reentry / nothing for other tables)
"""
from __future__ import annotations

import argparse

import pandas as pd

import ribbon_filter_test as ft
import ribbon_trend_backtest as rb

STOP, COST, MAX_SIGNALS = 60.0, 2.0, 2


SENSEX_CACHE = ft.CACHE.with_name("SENSEX_5minute_1y.csv")
SENSEX_SCALE = 3.2     # Sensex points per Nifty point (index ratio ~3.2); 1 Sensex lot (20) ~ 1 Nifty lot (65)


def yahoo_recent(symbol: str = "%5ENSEI") -> pd.DataFrame | None:
    try:
        import requests
        r = requests.get(f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}?range=60d&interval=5m",
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=20).json()["chart"]["result"][0]
        q = r["indicators"]["quote"][0]
        return pd.DataFrame({"ts": pd.to_datetime(r["timestamp"], unit="s", utc=True), "open": q["open"],
                             "high": q["high"], "low": q["low"], "close": q["close"]})
    except Exception as exc:
        print(f"(Yahoo top-up failed: {exc} -- using the cached data only)")
        return None


MULTI_CACHE = ft.CACHE.with_name("NIFTY50_5minute_multiyear.csv")


def multiyear(years: int, download: bool, book: bool = False, rally: bool = False) -> None:
    """The live rule and the main filter ideas, year by year. Each calendar year is run on its own
    with prices rescaled so its median close is 25,000 -- the 60-pt stop, 120-pt first hour, 20-pt
    EMA buffer and the trails then mean the same % move in every year. Results are in those
    'today-sized' Nifty points."""
    if download or not MULTI_CACHE.exists():
        ft.download("NSE:NIFTY 50", MULTI_CACHE, days=int(years * 365.25) + 40)
    d = ft.normalize(pd.read_csv(MULTI_CACHE))
    y = yahoo_recent()
    if y is not None:
        y = ft.normalize(y)
        d = pd.concat([d, y[y.ts > d.ts.max()]], ignore_index=True)
    live = dict(exit_mode="touch", touch_buf=20)
    lt = {**live, "trail": (150, 80)}
    cy = {**live, "hold": True, "carry_min": 0, "trail": (200, 100)}
    variants = [("LIVE intraday", lt), ("no EMA50 needed (earlier entry)", {**lt, "stack": "9-21"}),
                ("skip if RSI beyond 75/25", {**lt, "rsi_cap": 75}), ("skip if day moved > 250", {**lt, "max_day_move": 250}),
                ("skip if > 100 pts from EMA21", {**lt, "max_ext": 100}),
                ("20-pt pullback entry (6 candles)", {**lt, "pullback": 20, "pb_bars": 6}),
                ("old exit: close through EMA21, no trail", dict(exit_mode="close")),
                ("CARRY setup", cy), ("CARRY, skip if RSI beyond 80/20", {**cy, "rsi_cap": 80})]
    if rally:           # riding a multi-day rally: slower exits for trades that are carried overnight
        slow = {"exit_mode": "none", "hold": True, "carry_min": 0, "ema50_buf": 20}
        variants = [("LIVE intraday", lt), ("CARRY setup (paper now): EMA21 exit, trail 200/100", cy),
                    ("CARRY, EMA21 exit, no trailing stop", {**live, "hold": True, "carry_min": 0}),
                    ("CARRY, EMA21 exit, trail 400/200", {**live, "hold": True, "carry_min": 0, "trail": (400, 200)}),
                    ("CARRY, slow exit: 20 thru EMA50", slow),
                    ("CARRY, EMA50 exit + trail 400/200", {**slow, "trail": (400, 200)}),
                    ("CARRY, EMA50 exit + trail 600/300", {**slow, "trail": (600, 300)}),
                    ("HOLD everything (even losers), EMA50 exit", {"exit_mode": "none", "hold": True, "ema50_buf": 20})]
    if book:            # booking profit: fixed targets, a stop moved to the entry price, tighter trails
        variants = [("LIVE intraday", lt)]
        variants += [(f"book all at +{x}", {**lt, "target": x}) for x in (30, 40, 50, 60, 80, 100)]
        variants += [(f"stop to entry once +{x}", {**lt, "be": x}) for x in (30, 40, 60)]
        variants += [(f"trail {x}/{y}", {**live, "trail": (x, y)}) for x, y in ((40, 30), (60, 40), (80, 50))]
    yrs = sorted(set(d.ts.dt.year))
    out = {name: {} for name, _ in variants}
    info, alltr = {}, {name: [] for name, _ in variants}
    for yr in yrs:
        start = pd.Timestamp(yr, 1, 1) - pd.Timedelta(days=40)             # warm-up for the indicators
        part = d[(d.ts >= start) & (d.ts < pd.Timestamp(yr + 1, 1, 1))].copy()
        in_year = part[part.ts.dt.year == yr]
        if in_year.ts.dt.date.nunique() < 40:
            continue
        f = 25000 / in_year.close.median()
        part[["open", "high", "low", "close"]] *= f
        info[yr] = (in_year.ts.dt.date.nunique(), in_year.close.median())
        for name, kw in variants:
            t = simulate(part, **kw)
            t = t[pd.to_datetime(t.day).dt.year == yr]
            alltr[name].append(t)
            out[name][yr] = (len(t), t.pts.sum(), (t.pts > 0).mean() if len(t) else 0)
        print(f"  {yr} done ({info[yr][0]} days, Nifty around {info[yr][1]:,.0f})", flush=True)
    rows = []
    for name, _ in variants:
        r = {"version": name}
        for yr in info:
            n, tot, win = out[name][yr]
            r[str(yr)] = f"{tot:+.0f} ({win:.0%})"
        a = pd.concat(alltr[name], ignore_index=True)
        eq = a.pts.cumsum()
        r["TOTAL"] = round(a.pts.sum())
        r["trades"] = len(a)
        r["win"] = f"{(a.pts > 0).mean():.0%}"
        r["max_dd"] = round((eq.cummax() - eq).max())
        r["best_trade"], r["worst_trade"] = round(a.pts.max()), round(a.pts.min())
        r["losing_yrs"] = f"{sum(1 for v in out[name].values() if v[1] < 0)}/{len(info)}"
        rows.append(r)
    if book:            # half the lots book at the target, half follow the live rule
        base = pd.concat(alltr["LIVE intraday"], ignore_index=True)
        for x in (40, 60):
            tg = pd.concat(alltr[f"book all at +{x}"], ignore_index=True)
            both = pd.concat([base.assign(pts=base.pts / 2), tg.assign(pts=tg.pts / 2)]).sort_values("day", kind="stable")
            eq = both.pts.cumsum()
            r = {"version": f"HALF the lots book at +{x}, half run"}
            for yr in info:
                r[str(yr)] = f"{(out['LIVE intraday'][yr][1] + out[f'book all at +{x}'][yr][1]) / 2:+.0f}"
            r.update({"TOTAL": round(both.pts.sum()), "trades": "-", "win": "-", "max_dd": round((eq.cummax() - eq).max()),
                      "losing_yrs": "-"})
            rows.append(r)
    pd.set_option("display.width", 250)
    print("\nPoints per year in today-sized Nifty points (win rate in brackets); the first and last year may be partial:")
    print(pd.DataFrame(rows).to_string(index=False))
    if book:
        a = pd.concat(alltr["LIVE intraday"], ignore_index=True)
        lose = a[a.pts < 0]
        print(f"\nLIVE rule: {len(a)} trades, {len(lose)} ended at a loss. How far were the LOSERS in profit first?")
        print("  " + ", ".join(f"+{x} or more: {(lose.mfe >= x).mean():.0%}" for x in (20, 30, 40, 50, 60, 80)))
        win = a[a.pts > 0]
        print(f"  Winners: average +{win.pts.mean():.0f} pts, the best 10% made +{win.pts.quantile(0.9):.0f} or more "
              f"and hold {win.pts[win.pts >= win.pts.quantile(0.9)].sum() / a.pts.sum():.0%} of the total profit.")


def momentum(entry: str, s: int, last, prev, recent: list) -> bool:
    """The momentum condition on top of the EMA stack + RSI.
    macd          MACD histogram on the signal side and growing (LIVE rule)
    fisher_cross  Fisher Transform crossed its trigger in the signal direction on this candle
    fisher_cross3 ... on this candle or one of the 2 before
    fisher_state  Fisher above its trigger (buy) / below it (sell)
    none          no momentum condition"""
    if entry == "none":
        return True
    if entry == "macd":
        return last.mh * s > 0 and (last.mh - prev.mh) * s > 0
    if entry == "macd_pos":                     # histogram on the signal side, rising not required
        return last.mh * s > 0
    if entry == "fisher_state":
        return (last.fish - last.fish_trig) * s > 0
    bars = [last] if entry == "fisher_cross" else recent
    return any(b.fish_x == s for b in bars) and (last.fish - last.fish_trig) * s > 0


def simulate(d: pd.DataFrame, exit_mode: str = "close", touch_buf: float = 0.0,
             trail: tuple[float, float] | None = None, be: float | None = None,
             after_stop: str = "same", max_signals: int = MAX_SIGNALS, entry: str = "macd",
             tf: int = 10, stack: str = "9-21-50", ema9_buf: float | None = None, fisher_exit: bool = False,
             target: float | None = None, hold: bool = False, stop_pts: float = STOP,
             ema50_buf: float | None = None, carry_min: float | None = None,
             max_ext: float | None = None, pullback: float | str | None = None, pb_bars: int = 3,
             rsi_cap: float | None = None, max_day_move: float | None = None) -> pd.DataFrame:
    """after_stop: 'same' = no more signals that direction after a stop-loss (live),
    'all' = no more signals at all after a stop-loss, 'none' = no block,
    'once' = one trade per direction per day, whatever its result.
    tf: signal candle minutes (10 live, or 5). stack: "9-21-50" (live) or "9-21" (EMA50 not required).
    Extra exits: ema9_buf -> price goes that far through EMA9; fisher_exit -> a signal candle on which
    the Fisher Transform crosses against the trade; target -> take profit at entry +/- target pts.
    hold: carry the trade overnight -- no 15:10 exit; it ends only on the stop / EMA / trailing exits
    (a gap through an exit level fills at the open). stop_pts: stop distance. ema50_buf: price goes
    that far through EMA50. carry_min (with hold): at 15:10 the trade is carried overnight only if
    it is at least this many points in profit, otherwise it is closed like an intraday trade.
    max_ext: skip a signal whose close is more than this many points away from EMA21 (price already
    stretched -- an ordinary pullback to the average would hit the 60-pt stop first).
    Ways not to buy the top of a move that has already run:
    pullback: don't enter at the signal price -- place a limit `pullback` points better (or at EMA9
    with "ema9") and take the trade only if price comes back to it within pb_bars signal candles.
    rsi_cap: skip a BUY with RSI above it (a SELL with RSI below 100 - it).
    max_day_move: skip when price has already moved more than this from yesterday's close in the
    signal's direction."""
    pclose = d.groupby(d.ts.dt.date).close.last().shift(1)
    pending = None
    b = rb.bars10(d, tf)
    b["done"] = b.ts + pd.Timedelta(minutes=tf)
    h1 = rb.day_features(d, None)["hour1_range"]
    wide = (h1 >= ft.FIRST_HOUR_MIN).astype(int)
    trending = wide.rolling(ft.TREND_DAYS).sum().shift(1) >= ft.TREND_NEEDED
    known = wide.rolling(ft.TREND_DAYS).count().shift(1) >= ft.TREND_DAYS
    tenmin = b.set_index("done")
    out, pos, day_st, last, recent = [], None, {}, None, []
    for r in d.itertuples(index=False):
        t, day = r.ts, r.ts.date()
        st = day_st.setdefault(day, {"n": 0, "stopped": set(), "traded": set()})
        # 1) a 10-min candle finished at t: close-based exit, or a new signal
        if t in tenmin.index:
            prev, last = last, tenmin.loc[t]
            recent = (recent + [last])[-3:]
            if pos and pos["day"] != day and not hold:                     # intraday: never hold overnight
                out.append(dict(day=pos["day"], side=pos["side"], why="eod",
                                pts=(prev_close - pos["entry"]) * pos["side"] - COST))
                pos = None
            if pos and exit_mode == "close" and last.day == day and (
                    (pos["side"] > 0 and last.close < last.e21) or (pos["side"] < 0 and last.close > last.e21)):
                out.append(dict(day=day, side=pos["side"], why="ema21",
                                pts=(last.close - pos["entry"]) * pos["side"] - COST))
                pos = None
            elif pos and fisher_exit and last.day == day and last.fish_x == -pos["side"]:
                out.append(dict(day=day, side=pos["side"], why="fisher",
                                pts=(last.close - pos["entry"]) * pos["side"] - COST))
                pos = None
            elif not pos and prev is not None and last.day == day and known.get(day, False) \
                    and "09:35" <= last.hhmm < "14:30" and st["n"] < max_signals \
                    and (trending.get(day, False) or (last.hhmm >= "10:15" and h1.get(day, 0) >= ft.FIRST_HOUR_MIN)):
                full = stack == "9-21-50"
                up = last.close > last.e9 > last.e21 and (not full or last.e21 > last.e50) and last.rsi > 60
                dn = last.close < last.e9 < last.e21 and (not full or last.e21 < last.e50) and last.rsi < 40
                lg, sh = up and momentum(entry, 1, last, prev, recent), dn and momentum(entry, -1, last, prev, recent)
                side = 1 if lg else -1 if sh else 0
                if side and max_ext is not None and abs(last.close - last.e21) > max_ext:
                    side = 0
                if side and rsi_cap is not None and (last.rsi > rsi_cap if side > 0 else last.rsi < 100 - rsi_cap):
                    side = 0
                if side and max_day_move is not None and (last.close - pclose.get(day, last.close)) * side > max_day_move:
                    side = 0
                blocked = (after_stop == "same" and side in st["stopped"]) or (after_stop == "all" and st["stopped"]) \
                    or (after_stop == "once" and side in st["traded"])
                if side and not blocked and pullback is not None:
                    if pending is None:              # a resting limit order instead of buying the signal price
                        limit = last.e9 if pullback == "ema9" else last.close - side * pullback
                        pending = dict(side=side, limit=limit, day=day, until=t + pd.Timedelta(minutes=tf * pb_bars))
                elif side and not blocked:
                    pos = dict(side=side, entry=last.close, best=last.close, day=day,
                               stop=last.close - side * stop_pts)
                    st["n"] += 1
                    st["traded"].add(side)
        prev_close = r.close
        if pending and (pos or pending["day"] != day or t >= pending["until"]):
            pending = None
        if pending and ((pending["side"] > 0 and r.low <= pending["limit"]) or
                        (pending["side"] < 0 and r.high >= pending["limit"])):
            s, px = pending["side"], pending["limit"]
            px = min(r.open, px) if s > 0 else max(r.open, px)          # opened beyond the limit: a better fill
            pos = dict(side=s, entry=px, best=px, day=day, stop=px - s * stop_pts)
            st["n"] += 1
            st["traded"].add(s)
            pending = None
        if not pos or (pos["day"] != day and not hold):
            continue
        s = pos["side"]
        # 2) 15:10 exit at the price then
        if r.ts.strftime("%H:%M") >= "15:10" and (
                not hold or (carry_min is not None and (r.open - pos["entry"]) * s < carry_min)):
            out.append(dict(day=day, side=s, why="15:10", pts=(r.open - pos["entry"]) * s - COST,
                            nights=(day - pos["day"]).days, mfe=(pos["best"] - pos["entry"]) * s))
            pos = None
            continue
        # 3) price levels known before this 5-min candle; the first one hit exits
        levels = [(pos["stop"], "stop")]
        if exit_mode == "touch" and last is not None:
            levels.append((last.e21 - s * touch_buf, "touch"))
        if ema9_buf is not None and last is not None:
            levels.append((last.e9 - s * ema9_buf, "ema9"))
        if ema50_buf is not None and last is not None:
            levels.append((last.e50 - s * ema50_buf, "ema50"))
        if trail and (pos["best"] - pos["entry"]) * s >= trail[0]:
            levels.append((pos["best"] - s * trail[1], "trail"))
        lvl, why = max(levels, key=lambda x: x[0] * s)                    # nearest to price
        if (s > 0 and r.low <= lvl) or (s < 0 and r.high >= lvl):
            px = min(r.open, lvl) if s > 0 else max(r.open, lvl)            # a gap fills at the open
            out.append(dict(day=day, side=s, why=why, pts=(px - pos["entry"]) * s - COST,
                            nights=(day - pos["day"]).days, mfe=(pos["best"] - pos["entry"]) * s))
            if why == "stop" and px * s <= (pos["entry"] - s * stop_pts) * s + 1e-9:
                st["stopped"].add(s)
            pos = None
            continue
        if target:
            tgt = pos["entry"] + s * target
            if (s > 0 and r.high >= tgt) or (s < 0 and r.low <= tgt):
                px = max(r.open, tgt) if s > 0 else min(r.open, tgt)
                out.append(dict(day=day, side=s, why="target", pts=(px - pos["entry"]) * s - COST, mfe=target))
                pos = None
                continue
        pos["best"] = max(pos["best"], r.high) if s > 0 else min(pos["best"], r.low)
        if be and (pos["best"] - pos["entry"]) * s >= be:
            pos["stop"] = max(pos["stop"], pos["entry"]) if s > 0 else min(pos["stop"], pos["entry"])
    return pd.DataFrame(out, columns=["day", "side", "pts", "why", "nights", "mfe"]).fillna({"nights": 0})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv")
    ap.add_argument("--yahoo", help="Yahoo chart JSON only (60 days, quick check)")
    ap.add_argument("--index", choices=["nifty", "sensex"], default="nifty",
                    help="sensex: same rule on the Sensex, prices divided by 3.2 so every point setting "
                         "(60 stop, 20 EMA buffer, 120 first hour, trails) means the same %% move as on Nifty")
    ap.add_argument("--download", action="store_true",
                    help="(re)download the index's year of 5-min candles from Kite first (needs today's login)")
    ap.add_argument("--swing", action="store_true",
                    help="carry trades overnight (no 15:10 exit) with the live exits and wider variants")
    ap.add_argument("--multiyear", type=int, nargs="?", const=5, default=0, metavar="YEARS",
                    help="year-by-year check of the live rule and the main filter ideas over YEARS years "
                         "(default 5); downloads the history from Kite the first time (needs today's login)")
    ap.add_argument("--rally", action="store_true",
                    help="with --multiyear: slower exits for carried trades, to ride multi-day rallies")
    ap.add_argument("--book", action="store_true",
                    help="with --multiyear: profit-booking ideas (targets, stop to entry, tight trails, half lots)")
    ap.add_argument("--late", action="store_true",
                    help="ways not to buy the top: pullback (limit) entries, an RSI cap, a day-move cap")
    ap.add_argument("--ext", action="store_true",
                    help="skip signals where price is already stretched far from EMA21")
    ap.add_argument("--explore", action="store_true",
                    help="earlier entries, Fisher/EMA9/trail/target exits and 5-minute candles vs the live rule")
    ap.add_argument("--entry", action="store_true",
                    help="with the live exit, compare MACD vs Ehlers Fisher Transform as the entry momentum check")
    ap.add_argument("--reentry", action="store_true",
                    help="with the live exit, compare re-entry rules after a stop-loss")
    args = ap.parse_args()
    if args.multiyear:
        return multiyear(args.multiyear, args.download, args.book, args.rally)
    sensex = args.index == "sensex"
    if args.yahoo:
        d = ft.normalize(ft.load_yahoo(args.yahoo))
    else:
        cache = SENSEX_CACHE if sensex else (ft.CACHE if ft.CACHE.exists() else ft.OLD_CACHE)
        if args.download:
            ft.download("BSE:SENSEX" if sensex else "NSE:NIFTY 50", SENSEX_CACHE if sensex else ft.CACHE)
        elif sensex and not cache.exists() and not args.csv:
            raise SystemExit("No Sensex data yet -- run once with --download after the morning Kite login.")
        d = ft.normalize(pd.read_csv(args.csv or cache))
        y = yahoo_recent("%5EBSESN" if sensex else "%5ENSEI")
        if y is not None:
            y = ft.normalize(y)
            d = pd.concat([d, y[y.ts > d.ts.max()]], ignore_index=True)
    if sensex:
        d[["open", "high", "low", "close"]] /= SENSEX_SCALE
        print(f"SENSEX, prices / {SENSEX_SCALE}: results are in NIFTY-EQUIVALENT points "
              f"(x{SENSEX_SCALE} = Sensex points; x64 = rupees per Sensex lot of 20, about the same as a Nifty lot).")
    live = dict(exit_mode="touch", touch_buf=20)
    if args.swing:
        h = {**live, "hold": True}
        variants = [("INTRADAY (live): exit by 15:10", {**live, "trail": (150, 80)})]
        variants += [("HOLD overnight, live exits + trail 150/80", {**h, "trail": (150, 80)})]
        variants += [("HOLD, no trailing stop", h)]
        variants += [(f"HOLD, trail {x}/{y}", {**h, "trail": (x, y)}) for x, y in ((200, 100), (300, 150), (400, 200))]
        variants += [("HOLD, stop 100", {**h, "stop_pts": 100})]
        variants += [("HOLD, stop 100 + trail 300/150", {**h, "stop_pts": 100, "trail": (300, 150)})]
        variants += [("HOLD, exit 40 thru EMA21", {**h, "touch_buf": 40})]
        variants += [("HOLD, exit 40 thru EMA21 + trail 300/150", {**h, "touch_buf": 40, "trail": (300, 150)})]
        variants += [("HOLD, exit 20 thru EMA50", {"exit_mode": "none", "hold": True, "ema50_buf": 20})]
        variants += [("HOLD, EMA50 exit + trail 300/150", {"exit_mode": "none", "hold": True, "ema50_buf": 20, "trail": (300, 150)})]
        for x, y in ((150, 80), (200, 100), (300, 150)):
            variants += [(f"CARRY only if +{c} at 15:10, trail {x}/{y}", {**h, "trail": (x, y), "carry_min": c})
                         for c in (0, 50, 100)]
        return report(d, variants, swing=True)
    if args.late:
        lt = {**live, "trail": (150, 80)}
        cy = {**live, "hold": True, "carry_min": 0, "trail": (200, 100)}
        variants = [("LIVE intraday", lt)]
        variants += [(f"wait for a {p}-pt pullback ({n} candles)", {**lt, "pullback": p, "pb_bars": n})
                     for p in (20, 30, 40, 60) for n in (3, 6)]
        variants += [("wait for a pullback to EMA9 (6 candles)", {**lt, "pullback": "ema9", "pb_bars": 6})]
        variants += [(f"skip if RSI beyond {c}/{100 - c}", {**lt, "rsi_cap": c}) for c in (70, 75, 80)]
        variants += [(f"skip if day already moved > {x}", {**lt, "max_day_move": x}) for x in (150, 200, 250, 300)]
        variants += [("CARRY setup", cy)]
        variants += [(f"CARRY, {p}-pt pullback (6 candles)", {**cy, "pullback": p, "pb_bars": 6}) for p in (30, 40)]
        variants += [("CARRY, skip if RSI beyond 80/20", {**cy, "rsi_cap": 80})]
        variants += [("CARRY, skip if day moved > 200", {**cy, "max_day_move": 200})]
        return report(d, variants)
    if args.ext:
        lt = {**live, "trail": (150, 80)}
        variants = [("LIVE intraday (no limit)", lt)]
        variants += [(f"skip if > {x} pts from EMA21", {**lt, "max_ext": x}) for x in (120, 100, 90, 80, 70, 60, 50)]
        cy = {**live, "hold": True, "carry_min": 0, "trail": (200, 100)}
        variants += [("CARRY setup (no limit)", cy)]
        variants += [(f"CARRY, skip if > {x} pts from EMA21", {**cy, "max_ext": x}) for x in (120, 100, 80, 60)]
        return report(d, variants)
    if args.explore:
        variants = [("old: 10m, MACD, exit 20 thru EMA21", live)]
        variants += [("exit: Fisher turns against", {"exit_mode": "none", "fisher_exit": True})]
        variants += [("exit: Fisher OR 20 thru EMA21", {**live, "fisher_exit": True})]
        variants += [(f"exit: {n} thru EMA9", {"exit_mode": "none", "ema9_buf": n}) for n in (0, 10, 20)]
        variants += [(f"exit: EMA21 + trail {x}/{y}" + (" (LIVE NOW)" if (x, y) == (150, 80) else ""), {**live, "trail": (x, y)})
                     for x, y in ((80, 50), (100, 60), (150, 80))]
        variants += [(f"exit: EMA21 + target {x}", {**live, "target": x}) for x in (100, 150)]
        variants += [("entry: MACD hist >0 (no 'rising')", {**live, "entry": "macd_pos"})]
        variants += [("entry: EMA9>21 only (no EMA50)", {**live, "stack": "9-21"})]
        variants += [("entry: EMA9>21 + MACD hist >0", {**live, "stack": "9-21", "entry": "macd_pos"})]
        variants += [("5m candles, live rules", {**live, "tf": 5})]
        variants += [("5m, exit 10 thru EMA21", {**live, "tf": 5, "touch_buf": 10})]
        variants += [("5m, exit Fisher OR EMA21", {**live, "tf": 5, "fisher_exit": True})]
        variants += [("5m, MACD hist >0", {**live, "tf": 5, "entry": "macd_pos"})]
        variants += [("5m, 10m-style exit 20 thru EMA9", {"exit_mode": "none", "tf": 5, "ema9_buf": 20})]
        return report(d, variants)
    if args.entry:
        variants = [(f"{e}" + (" (LIVE NOW)" if e == "macd" else ""), {**live, "entry": e})
                    for e in ("macd", "fisher_cross", "fisher_cross3", "fisher_state", "none")]
        return report(d, variants)
    if args.reentry:
        variants = [("after stop: block same side (LIVE NOW)", live)]
        variants += [("after stop: 2 trades same side allowed", {**live, "after_stop": "none"})]
        variants += [("after stop: stop for the day", {**live, "after_stop": "all"})]
        variants += [("1 trade per direction per day", {**live, "after_stop": "once"})]
        variants += [("no block, max 3 a day", {**live, "after_stop": "none", "max_signals": 3})]
        variants += [("block same side, max 3 a day", {**live, "max_signals": 3})]
        variants += [("max 1 trade a day", {**live, "max_signals": 1})]
        return report(d, variants)
    variants = [("close through EMA21 (old rule)", dict())]
    variants += [(f"touch EMA21 +{n}" + (" (LIVE NOW)" if n == 20 else ""), dict(exit_mode="touch", touch_buf=n))
                 for n in (0, 10, 20, 30, 40)]
    variants += [(f"close + trail {x}/{y}", dict(trail=(x, y))) for x, y in
                 ((60, 40), (80, 60), (100, 60), (100, 80), (150, 80), (150, 100))]
    variants += [(f"close + breakeven at {x}", dict(be=x)) for x in (40, 60, 80)]
    variants += [(f"touch +10 + trail {x}/{y}", dict(exit_mode="touch", touch_buf=10, trail=(x, y)))
                 for x, y in ((100, 60), (150, 100))]
    report(d, variants)


def report(d: pd.DataFrame, variants: list, swing: bool = False) -> None:
    days = sorted(set(d.ts.dt.date))
    cut = days[int(len(days) * 2 / 3)]
    rows, last_day = [], days[-1]
    for name, kw in variants:
        t = simulate(d, **kw)
        a, tr, te = ft.stats(t), ft.stats(t[t.day < cut]), ft.stats(t[t.day >= cut])
        ld = t[t.day == last_day]
        row = {"exit": name, **a, "first2/3": tr["total"], "last1/3": te["total"]}
        if swing:
            row.update({"worst_trade": round(t.pts.min()) if len(t) else 0, "best_trade": round(t.pts.max()) if len(t) else 0,
                        "overnight%": f"{(t.nights > 0).mean():.0%}" if len(t) else "-",
                        "max_nights": int(t.nights.max()) if len(t) else 0})
        else:
            row[f"{last_day:%d%b}"] = " ".join(f"{p:+.0f}" for p in ld.pts) or "-"
        rows.append(row)
    pd.set_option("display.width", 220)
    print(f"\n{len(days)} days {days[0]} .. {days[-1]} (split at {cut}); points per 1 Nifty unit, after 2 pts cost")
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
