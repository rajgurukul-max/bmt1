"""Bollinger Band mean-reversion strategy.

Fades price that closes outside a rolling Bollinger Band (SMA +/- num_std * stddev
of closes), betting on reversion back toward the middle band. Bands and the SMA are
computed continuously across days (not reset daily) so they're warmed up from the
first trading day onward.

Entry (5-min candle close basis):
  - Long:  close < lower_band (SMA - num_std * std)
  - Short: close > upper_band (SMA + num_std * std)
Stop:   stop_pct % beyond entry, away from the band (reversion thesis invalidated).
Target: dynamic -- exits when price reverts back to the current SMA (middle band).
Guards: `cooldown_bars` after any exit before a new entry, `max_trades_per_day`, and
        the shared `square_off_time` from market config forces flat.
"""
from __future__ import annotations

from collections import deque
from datetime import date, datetime, time

from models import Candle, Side, Signal, SignalAction
from strategies.base import StrategyEngine


def _parse_time(value: str) -> time:
    hh, mm = value.split(":")
    return time(int(hh), int(mm))


class BollingerReversionEngine(StrategyEngine):
    def __init__(self, params: dict, qty: int, market_cfg):
        super().__init__(params, qty, market_cfg)

        self.square_off_t = _parse_time(market_cfg.square_off_time)
        self.period = int(params["period"])
        self.num_std = float(params["num_std"])
        self.stop_pct = float(params["stop_pct"])
        self.max_trades_per_day = int(params["max_trades_per_day"])
        self.cooldown_bars = int(params["cooldown_bars"])

        self._closes: deque[float] = deque(maxlen=self.period)

        self.current_day: date | None = None
        self._reset_day_state()

    def _reset_day_state(self) -> None:
        self.trades_today = 0
        self._bars_since_exit = self.cooldown_bars
        self.position: dict | None = None

    def on_new_day(self, trading_day: date) -> None:
        self.current_day = trading_day
        self._reset_day_state()

    @property
    def has_open_position(self) -> bool:
        return self.position is not None

    def _bands(self):
        if len(self._closes) < self.period:
            return None, None, None
        n = len(self._closes)
        mean = sum(self._closes) / n
        var = sum((c - mean) ** 2 for c in self._closes) / n
        std = var ** 0.5
        return mean, mean + self.num_std * std, mean - self.num_std * std

    def on_candle(self, candle: Candle, warmup: bool = False) -> list[Signal]:
        day = candle.timestamp.date()
        if self.current_day != day:
            self.on_new_day(day)

        sma, upper, lower = self._bands()
        self._closes.append(candle.close)

        if self._bars_since_exit < self.cooldown_bars:
            self._bars_since_exit += 1

        if warmup:
            return []

        signals: list[Signal] = []
        t = candle.timestamp.time()

        if t >= self.square_off_t:
            if self.position is not None:
                signals.append(self._close_position(candle.timestamp, candle.close, "square_off"))
            return signals

        if self.position is not None:
            signals.extend(self._manage_position(candle, sma))
            return signals

        if sma is None:
            return signals
        if self.trades_today >= self.max_trades_per_day:
            return signals
        if self._bars_since_exit < self.cooldown_bars:
            return signals
        if not self._trading_allowed():
            return signals

        if candle.close < lower:
            signals.append(self._open_position(Side.LONG, candle))
        elif candle.close > upper:
            signals.append(self._open_position(Side.SHORT, candle))

        return signals

    def _open_position(self, side: Side, candle: Candle) -> Signal:
        entry = candle.close
        dist = entry * self.stop_pct / 100.0
        stop = entry - dist if side == Side.LONG else entry + dist

        self.position = {"side": side, "entry_time": candle.timestamp, "entry_price": entry, "stop": stop}
        self.trades_today += 1
        return Signal(
            timestamp=candle.timestamp, side=side, action=SignalAction.ENTRY,
            price=entry, qty=self.qty, reason="bollinger_reversion",
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

    def _manage_position(self, candle: Candle, sma: float | None) -> list[Signal]:
        pos = self.position
        assert pos is not None
        side = pos["side"]
        signals: list[Signal] = []
        target = sma if sma is not None else pos["entry_price"]

        if side == Side.LONG:
            if candle.low <= pos["stop"]:
                signals.append(self._close_position(candle.timestamp, pos["stop"], "stop_loss"))
            elif candle.high >= target:
                signals.append(self._close_position(candle.timestamp, target, "band_reversion_target"))
        else:
            if candle.high >= pos["stop"]:
                signals.append(self._close_position(candle.timestamp, pos["stop"], "stop_loss"))
            elif candle.low <= target:
                signals.append(self._close_position(candle.timestamp, target, "band_reversion_target"))

        return signals
