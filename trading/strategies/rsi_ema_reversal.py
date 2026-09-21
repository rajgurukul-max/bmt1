"""RSI + EMA time-windowed reversal strategy (user-specified, 2026-09-21).

Two independent, mirrored setups, each on 5-min candles with a fixed
point-based stop/target (no trailing):

  Short: during [short_window_start, short_window_end), if RSI >= rsi_short_threshold
         AND close > EMA(ema_period) -> SELL. Target = entry - short_target_points.
         Stop = entry + short_stop_points.

  Long:  during [long_window_start, long_window_end), if RSI <= rsi_long_threshold
         AND close < EMA(ema_period) -> BUY. Target = entry + long_target_points.
         Stop = entry - long_stop_points.

This is a mean-reversion scalp: fading a moderate overbought/oversold reading
against the local EMA trend, restricted to the early-session window where the
first-hour analysis (hour1_analysis.py) showed most of the hour's range gets
established. At most one short and one long entry per day. RSI/EMA computed
continuously across days (not reset daily) so they're warmed up by the window.
All positions forced flat at `square_off_time`.
"""
from __future__ import annotations

from datetime import date, datetime, time

from models import Candle, Side, Signal, SignalAction
from strategies.base import StrategyEngine


def _parse_time(value: str) -> time:
    hh, mm = value.split(":")
    return time(int(hh), int(mm))


class RsiEmaReversalEngine(StrategyEngine):
    def __init__(self, params: dict, qty: int, market_cfg):
        super().__init__(params, qty, market_cfg)
        self.square_off_t = _parse_time(market_cfg.square_off_time)

        self.short_window_start = _parse_time(params["short_window_start"])
        self.short_window_end = _parse_time(params["short_window_end"])
        self.rsi_short_threshold = float(params["rsi_short_threshold"])
        self.short_target_points = float(params["short_target_points"])
        self.short_stop_points = float(params["short_stop_points"])

        self.long_window_start = _parse_time(params["long_window_start"])
        self.long_window_end = _parse_time(params["long_window_end"])
        self.rsi_long_threshold = float(params["rsi_long_threshold"])
        self.long_target_points = float(params["long_target_points"])
        self.long_stop_points = float(params["long_stop_points"])

        self.rsi_period = int(params["rsi_period"])
        self.ema_period = int(params["ema_period"])
        self._ema_k = 2 / (self.ema_period + 1)

        self._avg_gain: float | None = None
        self._avg_loss: float | None = None
        self._prev_close: float | None = None
        self._ema: float | None = None

        self.current_day: date | None = None
        self._reset_day_state()

    def _reset_day_state(self) -> None:
        self.traded_short = False
        self.traded_long = False
        self.position: dict | None = None

    def on_new_day(self, trading_day: date) -> None:
        self.current_day = trading_day
        self._reset_day_state()

    @property
    def has_open_position(self) -> bool:
        return self.position is not None

    def _update_indicators(self, candle: Candle) -> float | None:
        close = candle.close
        if self._prev_close is not None:
            change = close - self._prev_close
            gain = max(change, 0.0)
            loss = max(-change, 0.0)
            alpha = 1 / self.rsi_period
            if self._avg_gain is None:
                self._avg_gain, self._avg_loss = gain, loss
            else:
                self._avg_gain = gain * alpha + self._avg_gain * (1 - alpha)
                self._avg_loss = loss * alpha + self._avg_loss * (1 - alpha)
        self._prev_close = close

        self._ema = close if self._ema is None else close * self._ema_k + self._ema * (1 - self._ema_k)

        if self._avg_gain is None:
            return None
        if self._avg_loss == 0:
            return 100.0
        rs = self._avg_gain / self._avg_loss
        return 100 - 100 / (1 + rs)

    def on_candle(self, candle: Candle, warmup: bool = False) -> list[Signal]:
        day = candle.timestamp.date()
        if self.current_day != day:
            self.on_new_day(day)

        rsi = self._update_indicators(candle)
        ema = self._ema

        if warmup:
            return []

        signals: list[Signal] = []
        t = candle.timestamp.time()

        if t >= self.square_off_t:
            if self.position is not None:
                signals.append(self._close_position(candle.timestamp, candle.close, "square_off"))
            return signals

        if self.position is not None:
            signals.extend(self._manage_position(candle))
            return signals

        if rsi is None or ema is None or not self._trading_allowed():
            return signals

        if (
            self.short_window_start <= t < self.short_window_end
            and not self.traded_short
            and rsi >= self.rsi_short_threshold
            and candle.close > ema
        ):
            signals.append(self._open_position(Side.SHORT, candle))
        elif (
            self.long_window_start <= t < self.long_window_end
            and not self.traded_long
            and rsi <= self.rsi_long_threshold
            and candle.close < ema
        ):
            signals.append(self._open_position(Side.LONG, candle))

        return signals

    def _open_position(self, side: Side, candle: Candle) -> Signal:
        entry = candle.close
        if side == Side.SHORT:
            stop = entry + self.short_stop_points
            target = entry - self.short_target_points
            self.traded_short = True
        else:
            stop = entry - self.long_stop_points
            target = entry + self.long_target_points
            self.traded_long = True

        self.position = {
            "side": side, "entry_time": candle.timestamp, "entry_price": entry,
            "stop": stop, "target": target,
        }
        return Signal(
            timestamp=candle.timestamp, side=side, action=SignalAction.ENTRY,
            price=entry, qty=self.qty, reason="rsi_ema_reversal",
        )

    def _close_position(self, timestamp: datetime, price: float, reason: str) -> Signal:
        pos = self.position
        assert pos is not None
        side = pos["side"]
        self.position = None
        return Signal(
            timestamp=timestamp, side=side, action=SignalAction.EXIT,
            price=price, qty=self.qty, reason=reason,
        )

    def force_exit(self, timestamp: datetime, price: float, reason: str) -> Signal | None:
        if self.position is None:
            return None
        return self._close_position(timestamp, price, reason)

    def _manage_position(self, candle: Candle) -> list[Signal]:
        pos = self.position
        assert pos is not None
        side = pos["side"]
        signals: list[Signal] = []

        if side == Side.SHORT:
            if candle.high >= pos["stop"]:
                signals.append(self._close_position(candle.timestamp, pos["stop"], "stop_loss"))
            elif candle.low <= pos["target"]:
                signals.append(self._close_position(candle.timestamp, pos["target"], "target_hit"))
        else:
            if candle.low <= pos["stop"]:
                signals.append(self._close_position(candle.timestamp, pos["stop"], "stop_loss"))
            elif candle.high >= pos["target"]:
                signals.append(self._close_position(candle.timestamp, pos["target"], "target_hit"))

        return signals
