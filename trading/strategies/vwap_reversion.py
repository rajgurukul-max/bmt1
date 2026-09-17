"""VWAP mean-reversion strategy.

Structurally the opposite bet from ORB: instead of following a breakout, this fades
a price that has stretched meaningfully away from the session VWAP, expecting it to
revert back toward VWAP intraday.

Entry (5-min candle close basis), only after `min_bars_before_trade` candles so VWAP
has stabilized for the day:
  - Long:  close is >= band_pct % below VWAP (oversold stretch)
  - Short: close is >= band_pct % above VWAP (overbought stretch)
  Optionally requires volume below its trailing average (`require_below_avg_volume`),
  on the theory that a stretch on fading volume is exhaustion rather than a genuine
  breakout that would keep running.
Stop:   stop_pct % beyond entry, away from VWAP (the reversion thesis is invalidated).
Target: dynamic — exits when price reverts back to the current VWAP.
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


class VwapReversionEngine(StrategyEngine):
    def __init__(self, params: dict, qty: int, market_cfg):
        super().__init__(params, qty, market_cfg)

        self.square_off_t = _parse_time(market_cfg.square_off_time)
        self.band_pct = float(params["band_pct"])
        self.stop_pct = float(params["stop_pct"])
        self.min_bars_before_trade = int(params["min_bars_before_trade"])
        self.max_trades_per_day = int(params["max_trades_per_day"])
        self.cooldown_bars = int(params["cooldown_bars"])
        self.require_below_avg_volume = bool(params.get("require_below_avg_volume", True))

        self._volume_window: deque[float] = deque(maxlen=int(params["volume_avg_period"]))

        self.current_day: date | None = None
        self._reset_day_state()

    def _reset_day_state(self) -> None:
        self._cum_pv = 0.0
        self._cum_vol = 0.0
        self.bar_index = 0
        self.trades_today = 0
        self._bars_since_exit = self.cooldown_bars
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

        typical = (candle.high + candle.low + candle.close) / 3
        self._cum_pv += typical * candle.volume
        self._cum_vol += candle.volume
        vwap = self._cum_pv / self._cum_vol if self._cum_vol > 0 else candle.close

        vol_avg = None
        if len(self._volume_window) == self._volume_window.maxlen:
            vol_avg = sum(self._volume_window) / len(self._volume_window)
        self._volume_window.append(candle.volume)

        self.bar_index += 1
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
            signals.extend(self._manage_position(candle, vwap))
            return signals

        if self.bar_index < self.min_bars_before_trade:
            return signals
        if self.trades_today >= self.max_trades_per_day:
            return signals
        if self._bars_since_exit < self.cooldown_bars:
            return signals
        if not self._trading_allowed():
            return signals
        if self.require_below_avg_volume and (vol_avg is None or candle.volume >= vol_avg):
            return signals

        deviation_pct = (candle.close - vwap) / vwap * 100

        if deviation_pct <= -self.band_pct:
            signals.append(self._open_position(Side.LONG, candle))
        elif deviation_pct >= self.band_pct:
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
            price=entry, qty=self.qty, reason="vwap_reversion",
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

    def _manage_position(self, candle: Candle, vwap: float) -> list[Signal]:
        pos = self.position
        assert pos is not None
        side = pos["side"]
        signals: list[Signal] = []

        if side == Side.LONG:
            if candle.low <= pos["stop"]:
                signals.append(self._close_position(candle.timestamp, pos["stop"], "stop_loss"))
            elif candle.high >= vwap:
                signals.append(self._close_position(candle.timestamp, vwap, "vwap_reversion_target"))
        else:
            if candle.high >= pos["stop"]:
                signals.append(self._close_position(candle.timestamp, pos["stop"], "stop_loss"))
            elif candle.low <= vwap:
                signals.append(self._close_position(candle.timestamp, vwap, "vwap_reversion_target"))

        return signals
