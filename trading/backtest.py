"""Backtest the active strategy (default: ORB) over the locally cached history.

Usage:
    python data.py        # first, populate/update the local candle cache
    python backtest.py
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

import costs
from config import AppConfig, load_config
from data import load_cached_candles
from models import Candle, SignalAction, Side, Trade
from risk import RiskManager
from strategies import create_strategy_engine

logger = logging.getLogger(__name__)


def run_backtest(cfg: AppConfig, df: pd.DataFrame) -> list[Trade]:
    engine = create_strategy_engine(
        cfg.strategy.name, cfg.strategy.params, cfg.instrument.quantity, cfg.market
    )
    risk = RiskManager(cfg.risk.max_daily_loss, cfg.risk.kill_switch_file)
    engine.set_trade_gate(risk.is_trading_allowed)

    trades: list[Trade] = []
    open_entry = None  # dict with side/time/price while a position is open
    current_date = None

    for row in df.itertuples(index=False):
        candle = Candle(
            timestamp=row.date, open=row.open, high=row.high, low=row.low,
            close=row.close, volume=row.volume,
        )
        if current_date != candle.timestamp.date():
            current_date = candle.timestamp.date()
            risk.reset_day()

        for sig in engine.on_candle(candle):
            is_buy_fill = (sig.side == Side.LONG) == (sig.action == SignalAction.ENTRY)
            fill_price = costs.apply_slippage(sig.price, is_buy_fill, cfg.costs)

            if sig.action == SignalAction.ENTRY:
                open_entry = {"side": sig.side, "time": sig.timestamp, "price": fill_price}
            else:
                assert open_entry is not None and open_entry["side"] == sig.side
                entry_price = open_entry["price"]
                exit_price = fill_price
                qty = sig.qty
                sign = 1 if sig.side == Side.LONG else -1
                gross = (exit_price - entry_price) * qty * sign
                charges = costs.compute_charges(entry_price, exit_price, qty, sig.side, cfg.costs).total
                trade = Trade(
                    side=sig.side,
                    entry_time=open_entry["time"],
                    entry_price=entry_price,
                    exit_time=sig.timestamp,
                    exit_price=exit_price,
                    qty=qty,
                    exit_reason=sig.reason,
                    gross_pnl=gross,
                    charges=charges,
                )
                trades.append(trade)
                risk.register_realized_pnl(trade.net_pnl)
                open_entry = None

    return trades


def build_report(trades: list[Trade], reports_dir: Path) -> None:
    reports_dir.mkdir(parents=True, exist_ok=True)

    if not trades:
        print("No trades were generated over the backtest period.")
        return

    trades_df = pd.DataFrame(
        {
            "entry_time": [t.entry_time for t in trades],
            "exit_time": [t.exit_time for t in trades],
            "side": [t.side.value for t in trades],
            "entry_price": [t.entry_price for t in trades],
            "exit_price": [t.exit_price for t in trades],
            "qty": [t.qty for t in trades],
            "exit_reason": [t.exit_reason for t in trades],
            "gross_pnl": [t.gross_pnl for t in trades],
            "charges": [t.charges for t in trades],
            "net_pnl": [t.net_pnl for t in trades],
        }
    )
    trades_df.to_csv(reports_dir / "trades.csv", index=False)

    wins = trades_df[trades_df.net_pnl > 0]
    losses = trades_df[trades_df.net_pnl <= 0]
    win_rate = len(wins) / len(trades_df) * 100
    avg_win = wins.net_pnl.mean() if not wins.empty else 0.0
    avg_loss = losses.net_pnl.mean() if not losses.empty else 0.0

    equity = trades_df.net_pnl.cumsum()
    running_max = equity.cummax()
    drawdown = equity - running_max
    max_drawdown = drawdown.min()

    daily_pnl = (
        trades_df.assign(trade_date=trades_df.exit_time.dt.date)
        .groupby("trade_date")
        .net_pnl.sum()
    )
    daily_pnl.to_csv(reports_dir / "daily_pnl.csv", header=["net_pnl"])

    monthly_equity = (
        daily_pnl.groupby(pd.to_datetime(daily_pnl.index).to_period("M")).sum().cumsum()
    )
    monthly_equity.to_csv(reports_dir / "monthly_equity.csv", header=["cumulative_pnl"])

    print("=" * 60)
    print(f"Total trades       : {len(trades_df)}")
    print(f"Win rate           : {win_rate:.1f}%")
    print(f"Average win        : Rs {avg_win:,.2f}")
    print(f"Average loss       : Rs {avg_loss:,.2f}")
    print(f"Total net P&L      : Rs {equity.iloc[-1]:,.2f}")
    print(f"Max drawdown       : Rs {max_drawdown:,.2f}")
    print(f"Total charges paid : Rs {trades_df.charges.sum():,.2f}")
    print("-" * 60)
    print("Daily P&L distribution:")
    print(daily_pnl.describe().to_string())
    print("-" * 60)
    print("Monthly cumulative equity:")
    print(monthly_equity.to_string())
    print("=" * 60)
    print(f"Details written to {reports_dir}/")

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(trades_df.exit_time, equity)
    ax.set_title("Equity curve (per trade)")
    ax.set_ylabel("Cumulative net P&L (Rs)")
    fig.tight_layout()
    fig.savefig(reports_dir / "equity_curve.png")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 4))
    daily_pnl.hist(bins=30, ax=ax)
    ax.set_title("Daily P&L distribution")
    ax.set_xlabel("Net P&L (Rs)")
    fig.tight_layout()
    fig.savefig(reports_dir / "daily_pnl_hist.png")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 4))
    monthly_equity.plot(kind="bar", ax=ax)
    ax.set_title("Monthly cumulative equity")
    ax.set_ylabel("Cumulative net P&L (Rs)")
    fig.tight_layout()
    fig.savefig(reports_dir / "monthly_equity.png")
    plt.close(fig)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--reports-dir", default=None)
    args = parser.parse_args()

    cfg = load_config()
    df = load_cached_candles(cfg)
    if df.empty:
        raise SystemExit(
            "No cached candles found. Run `python data.py` first to download history."
        )

    trades = run_backtest(cfg, df)
    reports_dir = Path(args.reports_dir) if args.reports_dir else cfg.raw.get("reports_dir", None)
    reports_dir = Path(reports_dir) if reports_dir else (Path(__file__).resolve().parent / "reports")
    build_report(trades, reports_dir)


if __name__ == "__main__":
    main()
