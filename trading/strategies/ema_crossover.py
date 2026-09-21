"""EMA crossover trend-following strategy (whole trading day, let winners run).

Two EMAs of closing price, computed continuously across days:
  - Long:  fast EMA crosses above slow EMA -> BUY.
  - Short: fast EMA crosses below slow EMA -> SELL.

At most one position open at a time. Initial hard stop is `atr_mult` * ATR(atr_period)
away from entry (volatility-scaled, not a fixed point/percent distance). Once price
has moved `trail_activate_atr` * ATR in favor, the stop trails behind the fast EMA
instead, letting the trade ride the trend until either the trail is breached or the
opposite crossover fires. No profit target -- the exit is the trend reversing.
All positions forced flat at `square_off_time`. `min_gap_bars` prevents immediately
re-entering on a whipsaw right after an exit.
"""
from __future__ import annotations

from datetime import date, datetime, time

from models import Candle, Side, Signal, SignalAction
from strategies.base import StrategyEngine


def _parse_time(value: str) -> time:
    hh, mm = value.split(":")
    return time(int(hh), int(mm))


class EmaCrossoverEngine(StrategyEngine):
    def __init__(self, params: dict, qty: int, market_cfg):
        super().__init__(params, qty, market_cfg)

        self.square_off_t = _parse_time(market_cfg.square_off_time)
        self.fast_period = int(params["fast_period"])
        self.slow_period = int(params["slow_period"])
        self.atr_period = int(params["atr_period"])
        self.atr_mult = float(params["atr_mult"])
        self.trail_activate_atr = float(params["trail_activate_atr"])
        self.min_gap_bars = int(params.get("min_gap_bars", 0))

        self._fast_k = 2 / (self.fast_period + 1)
        self._slow_k = 2 / (self.slow_period + 1)
        self._atr_k = 1 / self.atr_period

        self._fast_ema: float | None = None
        self._slow_ema: float | None = None
        self._prev_fast: float | None = None
        self._prev_slow: float | None = None
        self._prev_close: float | None = None
        self._atr: float | None = None

        self.current_day: date | None = None
        self._reset_day_state()

    def _reset_day_state(self) -> None:
        self._bars_since_exit = self.min_gap_bars
        self.position: dict | None = None

    def on_new_day(self, trading_day: date) -> None:
        self.current_day = trading_day
        self._reset_day_state()

    @property
    def has_open_position(self) -> bool:
        return self.position is not None

    def _update_indicators(self, candle: Candle) -> None:
        close = candle.close
        self._fast_ema = close if self._fast_ema is None else close * self._fast_k + self._fast_ema * (1 - self._fast_k)
        self._slow_ema = close if self._slow_ema is None else close * self._slow_k + self._slow_ema * (1 - self._slow_k)

        if self._prev_close is not None:
            tr = max(
                candle.high - candle.low,
                abs(candle.high - self._prev_close),
                abs(candle.low - self._prev_close),
            )
            self._atr = tr if self._atr is None else tr * self._atr_k + self._atr * (1 - self._atr_k)
        self._prev_close = close

    def on_candle(self, candle: Candle, warmup: bool = False) -> list[Signal]:
        day = candle.timestamp.date()
        if self.current_day != day:
            self.on_new_day(day)

        prev_fast, prev_slow = self._fast_ema, self._slow_ema
        self._update_indicators(candle)

        if self._bars_since_exit < self.min_gap_bars:
            self._bars_since_exit += 1

        if warmup:
            return []

        signals: list[Signal] = []
        t = candle.timestamp.time()

        if t >= self.square_off_t:
            if self.position is not None:
                signals.append(self._close_position(candle.timestamp, candle.close, "square_off"))
            return signals

        crossed_up = prev_fast is not None and prev_fast <= prev_slow and self._fast_ema > self._slow_ema
        crossed_down = prev_fast is not None and prev_fast >= prev_slow and self._fast_ema < self._slow_ema

        if self.position is not None:
            # Exit on opposite crossover before managing stop/trail.
            side = self.position["side"]
            if (side == Side.LONG and crossed_down) or (side == Side.SHORT and crossed_up):
                signals.append(self._close_position(candle.timestamp, candle.close, "crossover_exit"))
                return signals
            signals.extend(self._manage_position(candle))
            return signals

        if self._atr is None or not self._trading_allowed():
            return signals
        if self._bars_since_exit < self.min_gap_bars:
            return signals

        if crossed_up:
            signals.append(self._open_position(Side.LONG, candle))
        elif crossed_down:
            signals.append(self._open_position(Side.SHORT, candle))

        return signals

    def _open_position(self, side: Side, candle: Candle) -> Signal:
        entry = candle.close
        dist = self.atr_mult * self._atr
        stop = entry - dist if side == Side.LONG else entry + dist

        self.position = {
            "side": side, "entry_time": candle.timestamp, "entry_price": entry,
            "stop": stop, "trailing_active": False,
        }
        return Signal(
            timestamp=candle.timestamp, side=side, action=SignalAction.ENTRY,
            price=entry, qty=self.qty, reason="ema_crossover",
        )

    def _close_position(self, timestamp: datetime, price: float, reason: str) -> Signal:
        pos = self.position
        assert pos is not None
        side = pos["side"]
        self.position = None
        self._bars_since_exit = 0
        return Signal(timestamp=timestamp, side=side, action=SignalAction.EXIT, price=price, qty=self.qty, reason=reason)

    def force_exit(self, timestamp: datetime, price: float, reason: str) -> Signal | None:
        if self.position is None:
            return None
        return self._close_position(timestamp, price, reason)

    def _manage_position(self, candle: Candle) -> list[Signal]:
        pos = self.position
        assert pos is not None
        side = pos["side"]
        signals: list[Signal] = []
        activate_dist = self.trail_activate_atr * self._atr

        if side == Side.LONG:
            if not pos["trailing_active"] and candle.high - pos["entry_price"] >= activate_dist:
                pos["trailing_active"] = True
            if pos["trailing_active"]:
                pos["stop"] = max(pos["stop"], self._fast_ema)
            if candle.low <= pos["stop"]:
                signals.append(self._close_position(candle.timestamp, pos["stop"], "stop_loss" if not pos["trailing_active"] else "trail_exit"))
        else:
            if not pos["trailing_active"] and pos["entry_price"] - candle.low >= activate_dist:
                pos["trailing_active"] = True
            if pos["trailing_active"]:
                pos["stop"] = min(pos["stop"], self._fast_ema)
            if candle.high >= pos["stop"]:
                signals.append(self._close_position(candle.timestamp, pos["stop"], "stop_loss" if not pos["trailing_active"] else "trail_exit"))

        return signals
