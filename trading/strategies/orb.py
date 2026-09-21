"""Opening Range Breakout (ORB) strategy.

Range = high/low of the configured range window (default 09:15-09:30).
Entry (5-min candle close basis):
  - Long:  close > range_high AND close > VWAP AND volume > 20-bar avg volume
  - Short: close < range_low  AND close < VWAP AND volume > 20-bar avg volume
Stop:    the tighter (or wider, per config) of {range midpoint, stop_pct% of entry}.
Target:  entry + target_rr * initial_risk. Once hit, switch to trailing the
         `trail_ema_period` EMA of closes instead of booking immediately.
Skips the day entirely if the opening range is outside [min_range_pct, max_range_pct].
At most one long and one short entry per day. All positions forced flat at
`square_off_time`.

Optional trend filter (`trend_filter: "ema"`, off by default): only takes a long
breakout when price is above a longer `trend_ema_period` EMA, and only takes a
short breakdown when price is below it. Diagnosed need: on ANGELONE, ORB longs won
25% of the time vs. 53% for shorts during the underlying downtrend in our test
period -- this filter stops the strategy fighting the prevailing trend.
"""
from __future__ import annotations

from collections import deque
from datetime import date, datetime, time

from models import Candle, Side, Signal, SignalAction
from strategies.base import StrategyEngine


def _parse_time(value: str) -> time:
    hh, mm = value.split(":")
    return time(int(hh), int(mm))


class OpeningRangeBreakoutEngine(StrategyEngine):
    def __init__(self, params: dict, qty: int, market_cfg):
        super().__init__(params, qty, market_cfg)

        self.range_start_t = _parse_time(params["range_start"])
        self.range_end_t = _parse_time(params["range_end"])
        self.square_off_t = _parse_time(market_cfg.square_off_time)

        self.min_range_pct = float(params["min_range_pct"])
        self.max_range_pct = float(params["max_range_pct"])
        self.stop_pct = float(params["stop_pct"])
        self.stop_selection = params.get("stop_selection", "tighter")
        self.target_rr = float(params["target_rr"])

        ema_period = int(params["trail_ema_period"])
        self._ema_k = 2 / (ema_period + 1)
        self._ema: float | None = None

        self.trend_filter = params.get("trend_filter", "none")
        self._trend_ema: float | None = None
        if self.trend_filter == "ema":
            trend_period = int(params["trend_ema_period"])
            self._trend_ema_k = 2 / (trend_period + 1)

        self._volume_window: deque[float] = deque(maxlen=int(params["volume_avg_period"]))

        self.current_day: date | None = None
        self._reset_day_state()

    def _reset_day_state(self) -> None:
        self.range_high: float | None = None
        self.range_low: float | None = None
        self._range_midpoint: float | None = None
        self.range_locked = False
        self.day_skip = False
        self.traded_long = False
        self.traded_short = False
        self._cum_pv = 0.0
        self._cum_vol = 0.0
        self.position: dict | None = None

    def on_new_day(self, trading_day: date) -> None:
        self.current_day = trading_day
        self._reset_day_state()

    @property
    def has_open_position(self) -> bool:
        return self.position is not None

    def on_candle(self, candle: Candle, warmup: bool = False) -> list[Signal]:
        day = candle.timestamp.date()
        if self.current_day != day:
            self.on_new_day(day)

        t = candle.timestamp.time()

        typical = (candle.high + candle.low + candle.close) / 3
        self._cum_pv += typical * candle.volume
        self._cum_vol += candle.volume
        vwap = self._cum_pv / self._cum_vol if self._cum_vol > 0 else candle.close

        vol_avg = None
        if len(self._volume_window) == self._volume_window.maxlen:
            vol_avg = sum(self._volume_window) / len(self._volume_window)
        self._volume_window.append(candle.volume)

        self._ema = candle.close if self._ema is None else (
            candle.close * self._ema_k + self._ema * (1 - self._ema_k)
        )

        if self.trend_filter == "ema":
            self._trend_ema = candle.close if self._trend_ema is None else (
                candle.close * self._trend_ema_k + self._trend_ema * (1 - self._trend_ema_k)
            )

        if warmup:
            return []

        signals: list[Signal] = []

        if self.range_start_t <= t < self.range_end_t:
            if self.range_high is None:
                self.range_high, self.range_low = candle.high, candle.low
            else:
                self.range_high = max(self.range_high, candle.high)
                self.range_low = min(self.range_low, candle.low)
            return signals

        if not self.range_locked:
            self.range_locked = True
            if self.range_high is None or self.range_low is None:
                self.day_skip = True
            else:
                range_pct = (self.range_high - self.range_low) / self.range_low * 100
                if range_pct > self.max_range_pct or range_pct < self.min_range_pct:
                    self.day_skip = True
                self._range_midpoint = (self.range_high + self.range_low) / 2

        if t >= self.square_off_t:
            if self.position is not None:
                signals.append(self._close_position(candle.timestamp, candle.close, "square_off"))
            return signals

        if self.day_skip:
            return signals

        if self.position is not None:
            signals.extend(self._manage_position(candle))
            return signals

        if vol_avg is None or not self._trading_allowed():
            return signals

        if (
            candle.close > self.range_high
            and candle.close > vwap
            and candle.volume > vol_avg
            and not self.traded_long
            and self._trend_ok(Side.LONG, candle)
        ):
            signals.append(self._open_position(Side.LONG, candle))
        elif (
            candle.close < self.range_low
            and candle.close < vwap
            and candle.volume > vol_avg
            and not self.traded_short
            and self._trend_ok(Side.SHORT, candle)
        ):
            signals.append(self._open_position(Side.SHORT, candle))

        return signals

    def _trend_ok(self, side: Side, candle: Candle) -> bool:
        if self.trend_filter != "ema" or self._trend_ema is None:
            return True
        return candle.close > self._trend_ema if side == Side.LONG else candle.close < self._trend_ema

    def _stop_distance(self, entry: float) -> float:
        dist_mid = abs(entry - self._range_midpoint)
        dist_pct = entry * self.stop_pct / 100.0
        return min(dist_mid, dist_pct) if self.stop_selection == "tighter" else max(dist_mid, dist_pct)

    def _open_position(self, side: Side, candle: Candle) -> Signal:
        entry = candle.close
        dist = self._stop_distance(entry)

        if side == Side.LONG:
            stop = entry - dist
            target = entry + self.target_rr * dist
            self.traded_long = True
        else:
            stop = entry + dist
            target = entry - self.target_rr * dist
            self.traded_short = True

        self.position = {
            "side": side,
            "entry_time": candle.timestamp,
            "entry_price": entry,
            "stop": stop,
            "target": target,
            "trailing_active": False,
            "trailing_stop": None,
        }
        return Signal(
            timestamp=candle.timestamp,
            side=side,
            action=SignalAction.ENTRY,
            price=entry,
            qty=self.qty,
            reason="orb_breakout",
        )

    def _close_position(self, timestamp: datetime, price: float, reason: str) -> Signal:
        pos = self.position
        assert pos is not None
        side = pos["side"]
        self.position = None
        return Signal(
            timestamp=timestamp,
            side=side,
            action=SignalAction.EXIT,
            price=price,
            qty=self.qty,
            reason=reason,
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

        if side == Side.LONG:
            if not pos["trailing_active"]:
                if candle.low <= pos["stop"]:
                    signals.append(self._close_position(candle.timestamp, pos["stop"], "stop_loss"))
                    return signals
                if candle.high >= pos["target"]:
                    pos["trailing_active"] = True
                    pos["trailing_stop"] = self._ema
            if pos["trailing_active"]:
                pos["trailing_stop"] = max(pos["trailing_stop"], self._ema)
                if candle.low <= pos["stop"]:
                    signals.append(self._close_position(candle.timestamp, pos["stop"], "stop_loss"))
                elif candle.close < pos["trailing_stop"]:
                    signals.append(self._close_position(candle.timestamp, candle.close, "trail_exit"))
        else:
            if not pos["trailing_active"]:
                if candle.high >= pos["stop"]:
                    signals.append(self._close_position(candle.timestamp, pos["stop"], "stop_loss"))
                    return signals
                if candle.low <= pos["target"]:
                    pos["trailing_active"] = True
                    pos["trailing_stop"] = self._ema
            if pos["trailing_active"]:
                pos["trailing_stop"] = min(pos["trailing_stop"], self._ema)
                if candle.high >= pos["stop"]:
                    signals.append(self._close_position(candle.timestamp, pos["stop"], "stop_loss"))
                elif candle.close > pos["trailing_stop"]:
                    signals.append(self._close_position(candle.timestamp, candle.close, "trail_exit"))

        return signals
