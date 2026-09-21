"""Cross-sectional NSE100 ranking backtest.

Instead of testing a single-stock technical signal (ORB, VWAP reversion, RSI/EMA,
etc. -- all tested elsewhere in this project with no surviving edge), this ranks
the whole NSE100 universe every day by each stock's morning return relative to the
day's cross-sectional average (i.e. stock-specific move, with the common market
move subtracted out), then trades the extremes of that ranking:

  - momentum:     long the top-K performers, short the bottom-K (bet the morning's
                  leaders/laggards keep leading/lagging)
  - reversal:     short the top-K, long the bottom-K (bet on mean reversion)
  - long_top / long_bottom / short_top / short_bottom: single-leg variants of the
                  above, to isolate which side (if either) carries any edge

Entry at the `t1` decision time's close, exit at the `t2` close, equal capital per
position (`--capital-per-position`), using the exact same Zerodha cost/slippage
model as every other backtest in this project (costs.py). Requires the NSE100
universe already cached locally under data_cache/ (see screen_universe.py).

Usage:
    python cross_sectional_screen.py --sweep            # full param grid on train split
    python cross_sectional_screen.py --t1 09:30 --t2 15:10 --k 10 --direction momentum
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import itertools
import os

import pandas as pd

from config import load_config
import costs as costs_mod
from models import Side

REQUIRED_TIMES = [
    "09:15", "09:20", "09:25", "09:30", "09:35", "09:40", "09:45",
    "10:00", "10:15", "10:30", "11:00", "11:30",
    "13:00", "13:30", "14:00", "14:30", "15:00", "15:10",
]

# Chronological split used throughout this project's strategy validation: fit
# parameters on TRAIN only, and never trust a result until it's re-checked on TEST.
TRAIN_END = dt.date(2026, 6, 1)
TEST_START = dt.date(2026, 6, 2)


def load_wide_prices(cache_dir: str, exclude: tuple[str, ...] = ()) -> pd.DataFrame:
    files = sorted(glob.glob(os.path.join(cache_dir, "*_NSE_5minute.csv")))
    frames = []
    for f in files:
        sym = os.path.basename(f).split("_NSE_5minute.csv")[0]
        if sym in exclude:
            continue
        df = pd.read_csv(f, usecols=["date", "close"])
        df["date"] = pd.to_datetime(df["date"])
        df["time_str"] = df["date"].dt.strftime("%H:%M")
        df = df[df["time_str"].isin(REQUIRED_TIMES)]
        df["day"] = df["date"].dt.date
        df["symbol"] = sym
        frames.append(df[["day", "time_str", "symbol", "close"]])
    all_df = pd.concat(frames, ignore_index=True)
    return all_df.pivot_table(index=["day", "time_str"], columns="symbol", values="close")


def run_xsec(
    wide_close: pd.DataFrame,
    costs_cfg,
    t1: str,
    t2: str,
    k: int,
    direction: str,
    capital_per_position: float = 100_000,
    date_filter=None,
) -> dict:
    open_px = wide_close.xs("09:15", level="time_str")
    t1_px = wide_close.xs(t1, level="time_str")
    t2_px = wide_close.xs(t2, level="time_str")

    days = open_px.index
    if date_filter is not None:
        days = [d for d in days if date_filter(d)]

    daily_rows, trade_rows = [], []
    for day in days:
        if day not in t1_px.index or day not in t2_px.index:
            continue
        open_row, t1_row, t2_row = open_px.loc[day], t1_px.loc[day], t2_px.loc[day]
        valid = open_row.notna() & t1_row.notna() & t2_row.notna() & (open_row > 0) & (t1_row > 0)
        syms = open_row.index[valid]
        if len(syms) < 2 * k:
            continue

        ret_to_t1 = (t1_row[syms] / open_row[syms]) - 1.0
        rel_ret = ret_to_t1 - ret_to_t1.mean()  # subtract the day's common market move
        ranked = rel_ret.sort_values(ascending=False)
        top_syms, bottom_syms = ranked.index[:k], ranked.index[-k:]

        def leg_pnl(sym_list, side: Side):
            total, n = 0.0, 0
            for s in sym_list:
                is_buy_entry = side == Side.LONG
                entry_price = costs_mod.apply_slippage(t1_row[s], is_buy_entry, costs_cfg)
                exit_price = costs_mod.apply_slippage(t2_row[s], not is_buy_entry, costs_cfg)
                qty = int(capital_per_position // entry_price)
                if qty <= 0:
                    continue
                sign = 1 if side == Side.LONG else -1
                gross = (exit_price - entry_price) * qty * sign
                charges = costs_mod.compute_charges(entry_price, exit_price, qty, side, costs_cfg).total
                net = gross - charges
                total += net
                n += 1
                trade_rows.append({"day": day, "symbol": s, "side": side.value, "net_pnl": net})
            return total, n

        day_pnl, day_trades = 0.0, 0
        legs = {
            "momentum": [(top_syms, Side.LONG), (bottom_syms, Side.SHORT)],
            "reversal": [(top_syms, Side.SHORT), (bottom_syms, Side.LONG)],
            "long_top": [(top_syms, Side.LONG)],
            "long_bottom": [(bottom_syms, Side.LONG)],
            "short_top": [(top_syms, Side.SHORT)],
            "short_bottom": [(bottom_syms, Side.SHORT)],
        }[direction]
        for sym_list, side in legs:
            p, n = leg_pnl(sym_list, side)
            day_pnl += p
            day_trades += n

        daily_rows.append({"day": day, "net_pnl": day_pnl, "trades": day_trades})

    daily = pd.DataFrame(daily_rows)
    trades = pd.DataFrame(trade_rows)
    if daily.empty:
        return {"days": 0, "trades": 0, "net_pnl": 0.0, "win_rate": None}
    return {
        "days": len(daily),
        "trades": len(trades),
        "net_pnl": daily["net_pnl"].sum(),
        "win_rate": (trades["net_pnl"] > 0).mean() * 100 if not trades.empty else None,
        "avg_daily_pnl": daily["net_pnl"].mean(),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sweep", action="store_true", help="run the full param grid on the train split")
    parser.add_argument("--t1", default="09:30")
    parser.add_argument("--t2", default="15:10")
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--direction", default="momentum",
                         choices=["momentum", "reversal", "long_top", "long_bottom", "short_top", "short_bottom"])
    parser.add_argument("--capital-per-position", type=float, default=100_000)
    args = parser.parse_args()

    cfg = load_config()
    wide_close = load_wide_prices(cfg.data.cache_dir, exclude=(cfg.instrument.symbol,))
    print(f"Loaded {len(wide_close.columns)} symbols, {wide_close.index.get_level_values(0).nunique()} days")

    if args.sweep:
        t1_opts = ["09:20", "09:30", "09:45", "10:00", "10:30"]
        t2_opts = ["13:00", "14:00", "15:00", "15:10"]
        k_opts = [5, 10, 20]
        dir_opts = ["momentum", "reversal", "long_top", "long_bottom", "short_top", "short_bottom"]

        results = []
        for t1, t2, k, direction in itertools.product(t1_opts, t2_opts, k_opts, dir_opts):
            r = run_xsec(wide_close, cfg.costs, t1, t2, k, direction,
                         args.capital_per_position, date_filter=lambda d: d <= TRAIN_END)
            r.update({"t1": t1, "t2": t2, "k": k, "direction": direction})
            results.append(r)

        res = pd.DataFrame(results).sort_values("net_pnl", ascending=False)
        os.makedirs("reports", exist_ok=True)
        res.to_csv("reports/cross_sectional_sweep_train.csv", index=False)
        pd.set_option("display.width", 220)
        print("\nTOP 20 (TRAIN):")
        print(res.head(20).to_string(index=False))
        print(f"\nPositive combos: {(res.net_pnl > 0).sum()} / {len(res)}")
    else:
        r = run_xsec(wide_close, cfg.costs, args.t1, args.t2, args.k, args.direction, args.capital_per_position)
        print(r)


if __name__ == "__main__":
    main()
