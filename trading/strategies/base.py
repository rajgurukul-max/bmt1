"""Abstract strategy engine interface.

A StrategyEngine consumes one completed candle at a time (identical code path for
backtesting and live paper trading) and emits zero or more Signals. Add new
strategies by subclassing this and registering them in strategies/__init__.py, then
pointing `active_strategy` in config/config.yaml at the new name.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Callable, Optional

from models import Candle, Signal


class StrategyEngine(ABC):
    def __init__(self, params: dict, qty: int, market_cfg):
        self.params = params
        self.qty = qty
        self.market_cfg = market_cfg
        self.can_trade_fn: Optional[Callable[[], bool]] = None

    def set_trade_gate(self, can_trade_fn: Callable[[], bool]) -> None:
        """Backtest/paper_trader inject their RiskManager check here so the engine
        refuses new entries once the daily loss limit or kill switch is active."""
        self.can_trade_fn = can_trade_fn

    def _trading_allowed(self) -> bool:
        return self.can_trade_fn() if self.can_trade_fn else True

    @abstractmethod
    def on_new_day(self, trading_day: date) -> None:
        """Reset per-day state (opening range, trade-taken flags, etc.)."""

    @abstractmethod
    def on_candle(self, candle: Candle, warmup: bool = False) -> list[Signal]:
        """Process one completed candle and return any signals it produced.

        `warmup=True` means the candle is historical context fed in purely to seed
        rolling indicators (e.g. before the live session opens) — no real trading
        decisions should be recorded as taken, only indicator state updated.
        """

    @property
    @abstractmethod
    def has_open_position(self) -> bool:
        ...

    @abstractmethod
    def force_exit(self, timestamp, price: float, reason: str) -> Optional[Signal]:
        """Immediately close any open position (e.g. kill switch). Returns the exit
        Signal, or None if there was no open position."""
