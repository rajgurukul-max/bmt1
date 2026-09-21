"""Previous-day high/low breakout strategy.

Range = previous trading day's high/low (whole session, not just the open).
Entry (5-min candle close basis), only after `entry_start` and before `entry_end`:
  - Long:  close > prev_day_high AND volume > `volume_avg_period`-bar avg volume
  - Short: close < prev_day_low  AND volume > `volume_avg_period`-bar avg volume
Stop:    stop_pct % of entry price.
Target:  entry +/- target_rr * initial risk. No trailing.
At most one long and one short entry per day. All positions forced flat at
`square_off_time`.
"""
from __future__ import annotations

from collections import deque
from datetime import date, datetime, time

from models import Candle, Side, Signal, SignalAction
from strategies.base import StrategyEngine


def _parse_time(value: str) -> time:
    hh, mm = value.split(":")
    return time(int(hh), int(mm))


class PrevDayBreakoutEngine(StrategyEngine):
    def __init__(self, params: dict, qty: int, market_cfg):
        super().__init__(params, qty, market_cfg)

        self.square_off_t = _parse_time(market_cfg.square_off_time)
        self.entry_start_t = _parse_time(params.get("entry_start", market_cfg.open_time))
        self.entry_end_t = _parse_time(params.get("entry_end", market_cfg.square_off_time))
        self.stop_pct = float(params["stop_pct"])
        self.target_rr = float(params["target_rr"])

        self._volume_window: deque[float] = deque(maxlen=int(params["volume_avg_period"]))

        self.prev_day_high: float | None = None
        self.prev_day_low: float | None = None
        self._today_high: float | None = None
        self._today_low: float | None = None

        self.current_day: date | None = None
        self._reset_day_state()

    def _reset_day_state(self) -> None:
        self.traded_long = False
        self.traded_short = False
        self.position: dict | None = None

    def on_new_day(self, trading_day: date) -> None:
        # Roll yesterday's running high/low into "previous day" before resetting.
        if self._today_high is not None:
            self.prev_day_high, self.prev_day_low = self._today_high, self._today_low
        self._today_high, self._today_low = None, None
        self.current_day = trading_day
        self._reset_day_state()

    @property
    def has_open_position(self) -> bool:
        return self.position is not None

    def on_candle(self, candle: Candle, warmup: bool = False) -> list[Signal]:
        day = candle.timestamp.date()
        if self.current_day != day:
            self.on_new_day(day)

        self._today_high = candle.high if self._today_high is None else max(self._today_high, candle.high)
        self._today_low = candle.low if self._today_low is None else min(self._today_low, candle.low)

        vol_avg = None
        if len(self._volume_window) == self._volume_window.maxlen:
            vol_avg = sum(self._volume_window) / len(self._volume_window)
        self._volume_window.append(candle.volume)

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

        if self.prev_day_high is None or vol_avg is None or not self._trading_allowed():
            return signals
        if not (self.entry_start_t <= t < self.entry_end_t):
            return signals

        if (
            candle.close > self.prev_day_high
            and candle.volume > vol_avg
            and not self.traded_long
        ):
            signals.append(self._open_position(Side.LONG, candle))
        elif (
            candle.close < self.prev_day_low
            and candle.volume > vol_avg
            and not self.traded_short
        ):
            signals.append(self._open_position(Side.SHORT, candle))

        return signals

    def _open_position(self, side: Side, candle: Candle) -> Signal:
        entry = candle.close
        dist = entry * self.stop_pct / 100.0

        if side == Side.LONG:
            stop = entry - dist
            target = entry + self.target_rr * dist
            self.traded_long = True
        else:
            stop = entry + dist
            target = entry - self.target_rr * dist
            self.traded_short = True

        self.position = {"side": side, "entry_time": candle.timestamp, "entry_price": entry, "stop": stop, "target": target}
        return Signal(
            timestamp=candle.timestamp, side=side, action=SignalAction.ENTRY,
            price=entry, qty=self.qty, reason="prev_day_breakout",
        )

    def _close_position(self, timestamp: datetime, price: float, reason: str) -> Signal:
        pos = self.position
        assert pos is not None
        side = pos["side"]
        self.position = None
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

        if side == Side.LONG:
            if candle.low <= pos["stop"]:
                signals.append(self._close_position(candle.timestamp, pos["stop"], "stop_loss"))
            elif candle.high >= pos["target"]:
                signals.append(self._close_position(candle.timestamp, pos["target"], "target_hit"))
        else:
            if candle.high >= pos["stop"]:
                signals.append(self._close_position(candle.timestamp, pos["stop"], "stop_loss"))
            elif candle.low <= pos["target"]:
                signals.append(self._close_position(candle.timestamp, pos["target"], "target_hit"))

        return signals
