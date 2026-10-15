"""Search for an intraday Nifty rule that captures 100-200 points, on real
5-minute Nifty spot data (data_cache/"NIFTY 50_NSE_5minute.csv", ~1 year).

Families tested (one trade per day max, flat by 15:10, P&L in Nifty points
after COST points per round trip -- futures slippage + charges):
  orb      opening-range breakout: range of the first N minutes; trade the
           first 5-min close beyond it; stop at the other side of the range
  pdhl     previous-day high/low breakout, fixed stop
  ema      10-min EMA fast/slow cross, in the direction of the 50-EMA trend
  gap      gap of >= G% at the open: fade it (towards prev close) or follow it
  hour1    first-hour move >= X%: follow it (trend day) or fade it
  revert   after 11:00, price >= K points from the day's open: fade it
Each with targets of 100/150/200 points or none (hold to 15:10).

Settings are chosen on the TRAIN period (first 2/3 of days) and judged on the
TEST period (last 1/3), so the result isn't just the best of many tries.

Usage: python intraday_nifty_ideas.py
"""
from __future__ import annotations

import itertools

import numpy as np
import pandas as pd

SPOT_FILE = "data_cache/NIFTY 50_NSE_5minute.csv"
COST = 2.0          # points per round trip
EXIT = "15:10"
TARGETS = (100, 150, 200, None)


def load() -> list[tuple[object, pd.DataFrame]]:
    m = pd.read_csv(SPOT_FILE)
    m["ts"] = pd.to_datetime(m["date"])
    m["day"] = m.ts.dt.date
    m["hhmm"] = m.ts.dt.strftime("%H:%M")
    return [(d, g.reset_index(drop=True)) for d, g in m.groupby("day")]


def run_trade(g: pd.DataFrame, i: int, side: int, entry: float, stop: float | None, target: float | None) -> float:
    """Walk bars after index i; stop checked before target within a bar (conservative)."""
    for j in range(i + 1, len(g)):
        hi, lo = g.high[j], g.low[j]
        if stop is not None and ((side > 0 and lo <= stop) or (side < 0 and hi >= stop)):
            return (stop - entry) * side - COST
        if target is not None and ((side > 0 and hi >= entry + target) or (side < 0 and lo <= entry - target)):
            return target - COST
        if g.hhmm[j] >= EXIT:
            return (g.close[j] - entry) * side - COST
    return (g.close.iloc[-1] - entry) * side - COST


def orb(days, minutes, target, stop_mode):
    out = []
    end = (pd.Timestamp("09:15") + pd.Timedelta(minutes=minutes)).strftime("%H:%M")
    for _, g in days:
        rng = g[g.hhmm < end]
        if rng.empty:
            continue
        hi, lo = rng.high.max(), rng.low.min()
        for i in range(len(rng), len(g)):
            if g.hhmm[i] >= "14:30":
                break
            c = g.close[i]
            if c > hi or c < lo:
                side = 1 if c > hi else -1
                stop = (lo if side > 0 else hi) if stop_mode == "range" else (hi + lo) / 2
                out.append(run_trade(g, i, side, c, stop, target))
                break
    return out


def pdhl(days, target, stop_pts):
    out = []
    for k in range(1, len(days)):
        ph, pl = days[k - 1][1].high.max(), days[k - 1][1].low.min()
        g = days[k][1]
        for i in range(1, len(g)):
            if g.hhmm[i] >= "14:30":
                break
            c = g.close[i]
            if c > ph or c < pl:
                side = 1 if c > ph else -1
                out.append(run_trade(g, i, side, c, c - side * stop_pts, target))
                break
    return out


def ema(days, fast, slow, target, stop_pts):
    out = []
    prev_close = None
    for _, g in days:
        b = g.set_index("ts")[["open", "high", "low", "close"]].resample("10min").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna().reset_index()
        b["hhmm"] = b.ts.dt.strftime("%H:%M")
        seed = pd.concat([pd.Series([prev_close] * slow if prev_close else []), b.close], ignore_index=True)
        f = seed.ewm(span=fast, adjust=False).mean().iloc[-len(b):].reset_index(drop=True)
        s = seed.ewm(span=slow, adjust=False).mean().iloc[-len(b):].reset_index(drop=True)
        t = seed.ewm(span=50, adjust=False).mean().iloc[-len(b):].reset_index(drop=True)
        for i in range(2, len(b)):
            if b.hhmm[i] >= "14:30":
                break
            up = f[i - 1] <= s[i - 1] and f[i] > s[i] and b.close[i] > t[i]
            dn = f[i - 1] >= s[i - 1] and f[i] < s[i] and b.close[i] < t[i]
            if up or dn:
                side = 1 if up else -1
                out.append(run_trade(b, i, side, b.close[i], b.close[i] - side * stop_pts, target))
                break
        prev_close = g.close.iloc[-1]
    return out


def gap(days, gap_pct, mode, target, stop_pts):
    out = []
    for k in range(1, len(days)):
        pc = days[k - 1][1].close.iloc[-1]
        g = days[k][1]
        gp = g.open[0] / pc - 1
        if abs(gp) < gap_pct:
            continue
        side = (-1 if gp > 0 else 1) * (1 if mode == "fade" else -1)
        out.append(run_trade(g, 0, side, g.close[0], g.close[0] - side * stop_pts, target))  # enter 9:20
    return out


def hour1(days, move_pct, mode, target, stop_pts):
    out = []
    for _, g in days:
        idx = g.index[g.hhmm == "10:10"]
        if len(idx) == 0:
            continue
        i = idx[0]
        mv = g.close[i] / g.open[0] - 1
        if abs(mv) < move_pct:
            continue
        side = (1 if mv > 0 else -1) * (1 if mode == "follow" else -1)
        out.append(run_trade(g, i, side, g.close[i], g.close[i] - side * stop_pts, target))
    return out


def revert(days, k_pts, target, stop_pts):
    out = []
    for _, g in days:
        o = g.open[0]
        for i in range(len(g)):
            if g.hhmm[i] < "11:00":
                continue
            if g.hhmm[i] >= "14:30":
                break
            dev = g.close[i] - o
            if abs(dev) >= k_pts:
                side = -1 if dev > 0 else 1
                out.append(run_trade(g, i, side, g.close[i], g.close[i] - side * stop_pts, target))
                break
    return out


def grid():
    for m, t, sm in itertools.product((15, 30, 60), TARGETS, ("range", "mid")):
        yield f"orb {m}m stop={sm} tgt={t}", lambda d, m=m, t=t, sm=sm: orb(d, m, t, sm)
    for t, sp in itertools.product(TARGETS, (40, 60, 100)):
        yield f"pdhl stop={sp} tgt={t}", lambda d, t=t, sp=sp: pdhl(d, t, sp)
    for (fa, sl), t, sp in itertools.product(((9, 21), (5, 13), (13, 34)), TARGETS, (40, 60, 100)):
        yield f"ema {fa}/{sl} stop={sp} tgt={t}", lambda d, fa=fa, sl=sl, t=t, sp=sp: ema(d, fa, sl, t, sp)
    for gp, mode, t, sp in itertools.product((0.003, 0.005, 0.008), ("fade", "follow"), TARGETS, (60, 100)):
        yield f"gap {gp:.1%} {mode} stop={sp} tgt={t}", lambda d, gp=gp, mode=mode, t=t, sp=sp: gap(d, gp, mode, t, sp)
    for mv, mode, t, sp in itertools.product((0.003, 0.005, 0.008), ("follow", "fade"), TARGETS, (60, 100)):
        yield f"hour1 {mv:.1%} {mode} stop={sp} tgt={t}", lambda d, mv=mv, mode=mode, t=t, sp=sp: hour1(d, mv, mode, t, sp)
    for kp, t, sp in itertools.product((100, 150, 200), TARGETS, (60, 100)):
        yield f"revert {kp}pts stop={sp} tgt={t}", lambda d, kp=kp, t=t, sp=sp: revert(d, kp, t, sp)


def stats(p: list[float]) -> dict:
    a = np.array(p) if p else np.array([0.0])
    eq = a.cumsum()
    return dict(n=len(p), total=a.sum(), avg=a.mean(), win=(a > 0).mean(), hit100=(a >= 98).mean(),
                maxdd=(eq - np.maximum.accumulate(eq)).min())


def main() -> None:
    days = load()
    cut = int(len(days) * 2 / 3)
    train, test = days[:cut], days[cut:]
    print(f"{len(days)} days: train {train[0][0]}..{train[-1][0]} ({len(train)}), test {test[0][0]}..{test[-1][0]} ({len(test)})")
    print(f"costs {COST} pts/round trip; 1 Nifty point = Rs 65 per futures lot\n")
    rows = []
    for name, fn in grid():
        tr, te = stats(fn(train)), stats(fn(test))
        rows.append(dict(rule=name, family=name.split()[0], tr_n=tr["n"], tr_total=tr["total"], tr_avg=tr["avg"],
                         tr_win=tr["win"], te_n=te["n"], te_total=te["total"], te_avg=te["avg"], te_win=te["win"],
                         te_hit100=te["hit100"], te_maxdd=te["maxdd"]))
    r = pd.DataFrame(rows)
    r = r[r.tr_n >= 20]
    print(f"{len(rows)} rule variants tested; {(r.tr_total > 0).sum()} profitable in train, "
          f"{((r.tr_total > 0) & (r.te_total > 0)).sum()} profitable in BOTH train and test\n")
    pd.set_option("display.width", 200)
    fmt = {"tr_total": "{:+.0f}", "tr_avg": "{:+.1f}", "tr_win": "{:.0%}", "te_total": "{:+.0f}", "te_avg": "{:+.1f}",
           "te_win": "{:.0%}", "te_hit100": "{:.0%}", "te_maxdd": "{:.0f}"}
    def show(df):
        df = df.copy()
        for c, f in fmt.items():
            df[c] = df[c].map(f.format)
        print(df.to_string(index=False))
    print("Best variant of each family, chosen on TRAIN, with its TEST result:")
    best = r.loc[r.groupby("family").tr_total.idxmax()].sort_values("tr_total", ascending=False)
    show(best.drop(columns="family"))
    print("\nTop 10 on TRAIN overall, and how they did in TEST:")
    show(r.sort_values("tr_total", ascending=False).head(10).drop(columns="family"))
    r.to_csv("reports/intraday_nifty_ideas.csv", index=False)


if __name__ == "__main__":
    main()
