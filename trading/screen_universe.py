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


def summarize(symbol: str, trades, qty: int, capital_per_trade: float) -> dict:
    if not trades:
        return {
            "symbol": symbol, "qty": qty, "trades": 0, "win_rate": None, "net_pnl": 0.0,
            "return_pct": 0.0, "avg_win": None, "avg_loss": None, "max_drawdown": 0.0,
        }
    pnl = pd.Series([t.net_pnl for t in trades])
    equity = pnl.cumsum()
    wins = pnl[pnl > 0]
    losses = pnl[pnl <= 0]
    return {
        "symbol": symbol,
        "qty": qty,
        "trades": len(pnl),
        "win_rate": len(wins) / len(pnl) * 100,
        "net_pnl": equity.iloc[-1],
        "return_pct": equity.iloc[-1] / capital_per_trade * 100,
        "avg_win": wins.mean() if not wins.empty else 0.0,
        "avg_loss": losses.mean() if not losses.empty else 0.0,
        "max_drawdown": (equity - equity.cummax()).min(),
    }


def scan(cfg: AppConfig, symbols: list[str], skip_download: bool, capital_per_trade: float) -> pd.DataFrame:
    """Backtest every symbol sized to roughly equal capital exposure (not equal share
    count), so P&L is comparable across stocks of wildly different prices instead of
    being dominated by whichever stock happens to be most expensive per share."""
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

            typical_price = df["close"].median()
            qty = max(1, round(capital_per_trade / typical_price))
            cfg.instrument.quantity = qty

            trades = run_backtest(cfg, df)
            rows.append(summarize(symbol, trades, qty, capital_per_trade))
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
    parser.add_argument(
        "--capital-per-trade", type=float, default=300_000,
        help="Notional capital per trade used to size qty per symbol, so P&L is "
             "comparable across stocks at very different prices (default: Rs 3,00,000, "
             "roughly 1000 shares of a Rs 300 stock).",
    )
    args = parser.parse_args()

    cfg = load_config()
    symbols = load_universe(Path(args.universe_file))
    logger.info(
        "Screening %d symbols with strategy '%s' at Rs %.0f capital/trade",
        len(symbols), cfg.strategy.name, args.capital_per_trade,
    )

    results = scan(cfg, symbols, args.skip_download, args.capital_per_trade)

    reports_dir = Path(args.reports_dir) if args.reports_dir else Path(__file__).resolve().parent / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    out_path = reports_dir / "universe_scan.csv"
    results.sort_values("return_pct", ascending=False).to_csv(out_path, index=False)

    ranked = results[results.trades >= MIN_TRADES_FOR_RANKING].sort_values("return_pct", ascending=False)

    pd.set_option("display.width", 160)
    print("=" * 70)
    print(f"Screened {len(results)} symbols ({(results.trades >= MIN_TRADES_FOR_RANKING).sum()} with >= {MIN_TRADES_FOR_RANKING} trades)")
    print(f"Each symbol sized to ~Rs {args.capital_per_trade:,.0f} notional per trade (see 'qty' column)")
    print(f"Full leaderboard written to {out_path}")
    print("-" * 70)
    print(f"TOP {args.top} by return % on capital (min {MIN_TRADES_FOR_RANKING} trades):")
    print(ranked.head(args.top).to_string(index=False))
    print("-" * 70)
    print(f"BOTTOM {args.top} by return % on capital (min {MIN_TRADES_FOR_RANKING} trades):")
    print(ranked.tail(args.top).to_string(index=False))
    print("=" * 70)


if __name__ == "__main__":
    main()
