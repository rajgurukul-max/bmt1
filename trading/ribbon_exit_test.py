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
"""
from __future__ import annotations

import argparse

import pandas as pd

import ribbon_filter_test as ft
import ribbon_trend_backtest as rb

STOP, COST, MAX_SIGNALS = 60.0, 2.0, 2


def yahoo_recent() -> pd.DataFrame | None:
    try:
        import requests
        r = requests.get("https://query2.finance.yahoo.com/v8/finance/chart/%5ENSEI?range=60d&interval=5m",
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=20).json()["chart"]["result"][0]
        q = r["indicators"]["quote"][0]
        return pd.DataFrame({"ts": pd.to_datetime(r["timestamp"], unit="s", utc=True), "open": q["open"],
                             "high": q["high"], "low": q["low"], "close": q["close"]})
    except Exception as exc:
        print(f"(Yahoo top-up failed: {exc} -- using the cached data only)")
        return None


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
             target: float | None = None) -> pd.DataFrame:
    """after_stop: 'same' = no more signals that direction after a stop-loss (live),
    'all' = no more signals at all after a stop-loss, 'none' = no block,
    'once' = one trade per direction per day, whatever its result.
    tf: signal candle minutes (10 live, or 5). stack: "9-21-50" (live) or "9-21" (EMA50 not required).
    Extra exits: ema9_buf -> price goes that far through EMA9; fisher_exit -> a signal candle on which
    the Fisher Transform crosses against the trade; target -> take profit at entry +/- target pts."""
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
            if pos and pos["day"] != day:                                  # never hold overnight
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
                blocked = (after_stop == "same" and side in st["stopped"]) or (after_stop == "all" and st["stopped"]) \
                    or (after_stop == "once" and side in st["traded"])
                if side and not blocked:
                    pos = dict(side=side, entry=last.close, best=last.close, day=day,
                               stop=last.close - side * STOP)
                    st["n"] += 1
                    st["traded"].add(side)
        prev_close = r.close
        if not pos or pos["day"] != day:
            continue
        s = pos["side"]
        # 2) 15:10 exit at the price then
        if r.ts.strftime("%H:%M") >= "15:10":
            out.append(dict(day=day, side=s, why="15:10", pts=(r.open - pos["entry"]) * s - COST))
            pos = None
            continue
        # 3) price levels known before this 5-min candle; the first one hit exits
        levels = [(pos["stop"], "stop")]
        if exit_mode == "touch" and last is not None:
            levels.append((last.e21 - s * touch_buf, "touch"))
        if ema9_buf is not None and last is not None:
            levels.append((last.e9 - s * ema9_buf, "ema9"))
        if trail and (pos["best"] - pos["entry"]) * s >= trail[0]:
            levels.append((pos["best"] - s * trail[1], "trail"))
        lvl, why = max(levels, key=lambda x: x[0] * s)                    # nearest to price
        if (s > 0 and r.low <= lvl) or (s < 0 and r.high >= lvl):
            px = min(r.open, lvl) if s > 0 else max(r.open, lvl)            # a gap fills at the open
            out.append(dict(day=day, side=s, why=why, pts=(px - pos["entry"]) * s - COST))
            if why == "stop" and px * s <= (pos["entry"] - s * STOP) * s + 1e-9:
                st["stopped"].add(s)
            pos = None
            continue
        if target:
            tgt = pos["entry"] + s * target
            if (s > 0 and r.high >= tgt) or (s < 0 and r.low <= tgt):
                px = max(r.open, tgt) if s > 0 else min(r.open, tgt)
                out.append(dict(day=day, side=s, why="target", pts=(px - pos["entry"]) * s - COST))
                pos = None
                continue
        pos["best"] = max(pos["best"], r.high) if s > 0 else min(pos["best"], r.low)
        if be and (pos["best"] - pos["entry"]) * s >= be:
            pos["stop"] = max(pos["stop"], pos["entry"]) if s > 0 else min(pos["stop"], pos["entry"])
    return pd.DataFrame(out, columns=["day", "side", "pts", "why"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv")
    ap.add_argument("--yahoo", help="Yahoo chart JSON only (60 days, quick check)")
    ap.add_argument("--explore", action="store_true",
                    help="earlier entries, Fisher/EMA9/trail/target exits and 5-minute candles vs the live rule")
    ap.add_argument("--entry", action="store_true",
                    help="with the live exit, compare MACD vs Ehlers Fisher Transform as the entry momentum check")
    ap.add_argument("--reentry", action="store_true",
                    help="with the live exit, compare re-entry rules after a stop-loss")
    args = ap.parse_args()
    if args.yahoo:
        d = ft.normalize(ft.load_yahoo(args.yahoo))
    else:
        d = ft.normalize(pd.read_csv(args.csv or (ft.CACHE if ft.CACHE.exists() else ft.OLD_CACHE)))
        y = yahoo_recent()
        if y is not None:
            y = ft.normalize(y)
            d = pd.concat([d, y[y.ts > d.ts.max()]], ignore_index=True)
    live = dict(exit_mode="touch", touch_buf=20)
    if args.explore:
        variants = [("LIVE: 10m, MACD, exit 20 thru EMA21", live)]
        variants += [("exit: Fisher turns against", {"exit_mode": "none", "fisher_exit": True})]
        variants += [("exit: Fisher OR 20 thru EMA21", {**live, "fisher_exit": True})]
        variants += [(f"exit: {n} thru EMA9", {"exit_mode": "none", "ema9_buf": n}) for n in (0, 10, 20)]
        variants += [(f"exit: EMA21 + trail {x}/{y}", {**live, "trail": (x, y)}) for x, y in ((80, 50), (100, 60), (150, 80))]
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


def report(d: pd.DataFrame, variants: list) -> None:
    days = sorted(set(d.ts.dt.date))
    cut = days[int(len(days) * 2 / 3)]
    rows, last_day = [], days[-1]
    for name, kw in variants:
        t = simulate(d, **kw)
        a, tr, te = ft.stats(t), ft.stats(t[t.day < cut]), ft.stats(t[t.day >= cut])
        ld = t[t.day == last_day]
        rows.append({"exit": name, **a, "first2/3": tr["total"], "last1/3": te["total"],
                     f"{last_day:%d%b}": " ".join(f"{p:+.0f}" for p in ld.pts) or "-"})
    pd.set_option("display.width", 220)
    print(f"\n{len(days)} days {days[0]} .. {days[-1]} (split at {cut}); points per 1 Nifty unit, after 2 pts cost")
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
