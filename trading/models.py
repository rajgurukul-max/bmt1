"""Shared data structures used by strategies, backtest.py and paper_trader.py."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Side(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class SignalAction(str, Enum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"


@dataclass
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Signal:
    timestamp: datetime
    side: Side
    action: SignalAction
    price: float
    qty: int
    reason: str


@dataclass
class Trade:
    side: Side
    entry_time: datetime
    entry_price: float
    exit_time: datetime
    exit_price: float
    qty: int
    exit_reason: str
    gross_pnl: float
    charges: float

    @property
    def net_pnl(self) -> float:
        return self.gross_pnl - self.charges
