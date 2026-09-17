"""Backtest the active strategy across a universe of symbols (default: NSE 100) and
rank them, so you can find which names the strategy actually works on instead of
running it blindly on one stock.

Usage:
    python screen_universe.py                      # download + backtest all symbols
    python screen_universe.py --skip-download       # reuse whatever is already cached
    python screen_universe.py --universe-file config/universe_nse100.txt
    python screen_universe.py --top 5

Writes a per-symbol leaderboard to reports/universe_scan.csv.
"""
from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

import pandas as pd

from backtest import run_backtest
from config import AppConfig, load_config
from data import get_kite_client, load_cached_candles, update_cache

logger = logging.getLogger(__name__)

DEFAULT_UNIVERSE_FILE = Path(__file__).resolve().parent / "config" / "universe_nse100.txt"
MIN_TRADES_FOR_RANKING = 15


def load_universe(path: Path) -> list[str]:
    with open(path) as fh:
        return [line.strip() for line in fh if line.strip() and not line.startswith("#")]


def summarize(symbol: str, trades) -> dict:
    if not trades:
        return {
            "symbol": symbol, "trades": 0, "win_rate": None, "net_pnl": 0.0,
            "avg_win": None, "avg_loss": None, "max_drawdown": 0.0,
        }
    pnl = pd.Series([t.net_pnl for t in trades])
    equity = pnl.cumsum()
    wins = pnl[pnl > 0]
    losses = pnl[pnl <= 0]
    return {
        "symbol": symbol,
        "trades": len(pnl),
        "win_rate": len(wins) / len(pnl) * 100,
        "net_pnl": equity.iloc[-1],
        "avg_win": wins.mean() if not wins.empty else 0.0,
        "avg_loss": losses.mean() if not losses.empty else 0.0,
        "max_drawdown": (equity - equity.cummax()).min(),
    }


def scan(cfg: AppConfig, symbols: list[str], skip_download: bool) -> pd.DataFrame:
    kite = None if skip_download else get_kite_client(cfg)
    rows = []

    for i, symbol in enumerate(symbols, 1):
        logger.info("[%d/%d] %s", i, len(symbols), symbol)
        try:
            if not skip_download:
                update_cache(cfg, kite=kite, symbol=symbol, exchange=cfg.instrument.exchange)
                time.sleep(cfg.data.request_pause_seconds)
            df = load_cached_candles(cfg, symbol=symbol, exchange=cfg.instrument.exchange)
            if df.empty:
                logger.warning("No data for %s, skipping.", symbol)
                continue
            trades = run_backtest(cfg, df)
            rows.append(summarize(symbol, trades))
        except Exception:
            logger.exception("Failed to process %s", symbol)

    return pd.DataFrame(rows)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--universe-file", default=str(DEFAULT_UNIVERSE_FILE))
    parser.add_argument("--skip-download", action="store_true", help="Reuse cached candles only.")
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--reports-dir", default=None)
    args = parser.parse_args()

    cfg = load_config()
    symbols = load_universe(Path(args.universe_file))
    logger.info("Screening %d symbols with strategy '%s'", len(symbols), cfg.strategy.name)

    results = scan(cfg, symbols, args.skip_download)

    reports_dir = Path(args.reports_dir) if args.reports_dir else Path(__file__).resolve().parent / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    out_path = reports_dir / "universe_scan.csv"
    results.sort_values("net_pnl", ascending=False).to_csv(out_path, index=False)

    ranked = results[results.trades >= MIN_TRADES_FOR_RANKING].sort_values("net_pnl", ascending=False)

    pd.set_option("display.width", 160)
    print("=" * 70)
    print(f"Screened {len(results)} symbols ({(results.trades >= MIN_TRADES_FOR_RANKING).sum()} with >= {MIN_TRADES_FOR_RANKING} trades)")
    print(f"Full leaderboard written to {out_path}")
    print("-" * 70)
    print(f"TOP {args.top} by net P&L (min {MIN_TRADES_FOR_RANKING} trades):")
    print(ranked.head(args.top).to_string(index=False))
    print("-" * 70)
    print(f"BOTTOM {args.top} by net P&L (min {MIN_TRADES_FOR_RANKING} trades):")
    print(ranked.tail(args.top).to_string(index=False))
    print("=" * 70)


if __name__ == "__main__":
    main()
