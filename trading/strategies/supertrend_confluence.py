"""Supertrend + RSI + Pivot-R1 + Bollinger confluence strategy (long only, user-specified).

Entry (5-min candle close basis), all four conditions must hold on the same candle:
  1. Supertrend(period, multiplier) is in an uptrend (close > current Supertrend value).
  2. RSI(rsi_period) >= rsi_threshold.
  3. Close is within `near_pct` % of the day's pivot R1 (classic pivot, computed from
     the *previous* trading day's H/L/C: pivot = (H+L+C)/3, R1 = 2*pivot - L).
  4. Close is within `near_pct` % of the upper Bollinger Band (SMA(bb_period) +
     bb_std * rolling stddev of closes).

Stop loss and exit: the current Supertrend value doubles as both the trailing stop
and the trend-reversal exit -- in the classic Supertrend indicator these are the same
event (the line flips from support to resistance exactly when close crosses below
it), so "stop near supertrend" and "exit if supertrend reverses" collapse into one
rule here: exit the instant Supertrend flips from uptrend to downtrend. This is a
design choice worth flagging since the user described them as two separate rules;
if a wider/tighter stop distinct from the flip itself is wanted, that would need a
different parameter (not implemented here).

Supertrend, RSI, and Bollinger Bands are all computed continuously across days (not
reset daily) so they're warmed up properly. Pivot R1 is recomputed once per day from
the prior day's completed candles. The first trading day in the data has no prior
day and is skipped entirely. All positions forced flat at `square_off_time`.
"""
from __future__ import annotations

from datetime import date, datetime, time

from models import Candle, Side, Signal, SignalAction
from strategies.base import StrategyEngine


def _parse_time(value: str) -> time:
    hh, mm = value.split(":")
    return time(int(hh), int(mm))


class SupertrendConfluenceEngine(StrategyEngine):
    def __init__(self, params: dict, qty: int, market_cfg):
        super().__init__(params, qty, market_cfg)

        self.square_off_t = _parse_time(market_cfg.square_off_time)

        self.st_period = int(params.get("supertrend_period", 10))
        self.st_mult = float(params.get("supertrend_mult", 3.0))
        self.rsi_period = int(params.get("rsi_period", 14))
        self.rsi_threshold = float(params.get("rsi_threshold", 65))
        self.bb_period = int(params.get("bb_period", 20))
        self.bb_std = float(params.get("bb_std", 2.0))
        self.near_pct = float(params.get("near_pct", 0.3))
        self.one_trade_per_day = bool(params.get("one_trade_per_day", False))

        # Supertrend state
        self._atr: float | None = None
        self._prev_close: float | None = None
        self._final_upper: float | None = None
        self._final_lower: float | None = None
        self._st_value: float | None = None
        self._st_uptrend: bool | None = None

        # RSI state
        self._avg_gain: float | None = None
        self._avg_loss: float | None = None
        self._rsi_prev_close: float | None = None

        # Bollinger state
        self._closes: list[float] = []

        # Pivot state
        self._prev_day_high: float | None = None
        self._prev_day_low: float | None = None
        self._prev_day_close: float | None = None
        self._today_high: float | None = None
        self._today_low: float | None = None
        self._pivot_r1: float | None = None

        self.current_day: date | None = None
        self._reset_day_state()

    def _reset_day_state(self) -> None:
        self.traded_today = False
        self.position: dict | None = None

    def on_new_day(self, trading_day: date) -> None:
        if self._today_high is not None:
            self._prev_day_high = self._today_high
            self._prev_day_low = self._today_low
            self._prev_day_close = self._prev_close
        self._today_high, self._today_low = None, None

        if self._prev_day_high is not None:
            pivot = (self._prev_day_high + self._prev_day_low + self._prev_day_close) / 3
            self._pivot_r1 = 2 * pivot - self._prev_day_low
        else:
            self._pivot_r1 = None

        self.current_day = trading_day
        self._reset_day_state()

    @property
    def has_open_position(self) -> bool:
        return self.position is not None

    def _update_supertrend(self, candle: Candle) -> None:
        if self._prev_close is not None:
            tr = max(
                candle.high - candle.low,
                abs(candle.high - self._prev_close),
                abs(candle.low - self._prev_close),
            )
            k = 1 / self.st_period
            self._atr = tr if self._atr is None else tr * k + self._atr * (1 - k)
        else:
            self._atr = candle.high - candle.low

        mid = (candle.high + candle.low) / 2
        basic_upper = mid + self.st_mult * self._atr
        basic_lower = mid - self.st_mult * self._atr

        prev_close = self._prev_close if self._prev_close is not None else candle.close

        if self._final_upper is None:
            self._final_upper = basic_upper
            self._final_lower = basic_lower
            self._st_uptrend = candle.close >= mid
        else:
            self._final_upper = (
                basic_upper if (basic_upper < self._final_upper or prev_close > self._final_upper) else self._final_upper
            )
            self._final_lower = (
                basic_lower if (basic_lower > self._final_lower or prev_close < self._final_lower) else self._final_lower
            )

            if self._st_uptrend:
                if candle.close < self._final_lower:
                    self._st_uptrend = False
            else:
                if candle.close > self._final_upper:
                    self._st_uptrend = True

        self._st_value = self._final_lower if self._st_uptrend else self._final_upper

    def _update_rsi(self, candle: Candle) -> float | None:
        close = candle.close
        if self._rsi_prev_close is not None:
            change = close - self._rsi_prev_close
            gain, loss = max(change, 0.0), max(-change, 0.0)
            alpha = 1 / self.rsi_period
            if self._avg_gain is None:
                self._avg_gain, self._avg_loss = gain, loss
            else:
                self._avg_gain = gain * alpha + self._avg_gain * (1 - alpha)
                self._avg_loss = loss * alpha + self._avg_loss * (1 - alpha)
        self._rsi_prev_close = close

        if self._avg_gain is None:
            return None
        if self._avg_loss == 0:
            return 100.0
        rs = self._avg_gain / self._avg_loss
        return 100 - 100 / (1 + rs)

    def _update_bollinger(self, candle: Candle) -> float | None:
        self._closes.append(candle.close)
        if len(self._closes) > self.bb_period:
            self._closes.pop(0)
        if len(self._closes) < self.bb_period:
            return None
        n = len(self._closes)
        mean = sum(self._closes) / n
        var = sum((c - mean) ** 2 for c in self._closes) / n
        std = var ** 0.5
        return mean + self.bb_std * std

    def on_candle(self, candle: Candle, warmup: bool = False) -> list[Signal]:
        day = candle.timestamp.date()
        if self.current_day != day:
            self.on_new_day(day)

        self._today_high = candle.high if self._today_high is None else max(self._today_high, candle.high)
        self._today_low = candle.low if self._today_low is None else min(self._today_low, candle.low)

        prev_uptrend = self._st_uptrend
        self._update_supertrend(candle)
        rsi = self._update_rsi(candle)
        bb_upper = self._update_bollinger(candle)
        self._prev_close = candle.close

        if warmup:
            return []

        signals: list[Signal] = []
        t = candle.timestamp.time()

        if t >= self.square_off_t:
            if self.position is not None:
                signals.append(self._close_position(candle.timestamp, candle.close, "square_off"))
            return signals

        # Supertrend flip from up to down is both the stop and the reversal exit.
        if self.position is not None:
            if prev_uptrend and not self._st_uptrend:
                signals.append(self._close_position(candle.timestamp, self._st_value, "supertrend_reversal"))
            return signals

        if self._pivot_r1 is None or rsi is None or bb_upper is None or not self._trading_allowed():
            return signals
        if self.one_trade_per_day and self.traded_today:
            return signals

        near_r1 = abs(candle.close - self._pivot_r1) / self._pivot_r1 * 100 <= self.near_pct
        near_bb_upper = abs(candle.close - bb_upper) / bb_upper * 100 <= self.near_pct

        if self._st_uptrend and rsi >= self.rsi_threshold and near_r1 and near_bb_upper:
            signals.append(self._open_position(candle))

        return signals

    def _open_position(self, candle: Candle) -> Signal:
        entry = candle.close
        self.position = {"side": Side.LONG, "entry_time": candle.timestamp, "entry_price": entry, "stop": self._st_value}
        self.traded_today = True
        return Signal(
            timestamp=candle.timestamp, side=Side.LONG, action=SignalAction.ENTRY,
            price=entry, qty=self.qty, reason="supertrend_confluence",
        )

    def _close_position(self, timestamp: datetime, price: float, reason: str) -> Signal:
        pos = self.position
        assert pos is not None
        self.position = None
        return Signal(timestamp=timestamp, side=pos["side"], action=SignalAction.EXIT, price=price, qty=self.qty, reason=reason)

    def force_exit(self, timestamp: datetime, price: float, reason: str) -> Signal | None:
        if self.position is None:
            return None
        return self._close_position(timestamp, price, reason)
