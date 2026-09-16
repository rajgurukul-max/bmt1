"""Live paper trading via Kite Ticker.

Streams real-time ticks for the configured symbol during market hours, builds
5-minute candles from them, feeds the same strategy engine used by backtest.py,
and logs every signal and simulated fill. NO REAL ORDERS ARE EVER PLACED — this
module never calls kite.place_order or any order-management endpoint.

Usage:
    python paper_trader.py
"""
from __future__ import annotations

import csv
import logging
import sys
import threading
import time as time_module
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytz
from kiteconnect import KiteTicker

import costs
from config import AppConfig, load_config
from data import get_instrument_token, get_kite_client
from models import Candle, Side, SignalAction, Signal, Trade
from risk import RiskManager
from strategies import create_strategy_engine

logger = logging.getLogger("paper_trader")


def _parse_time(value: str) -> time:
    hh, mm = value.split(":")
    return time(int(hh), int(mm))


class CandleAggregator:
    """Buckets ticks into completed 5-minute OHLCV candles."""

    def __init__(self, interval_minutes: int):
        self.interval_minutes = interval_minutes
        self.bucket_start: datetime | None = None
        self.o = self.h = self.l = self.c = None
        self._start_cum_volume = 0
        self._last_cum_volume = 0

    def _floor(self, ts: datetime) -> datetime:
        minute = (ts.minute // self.interval_minutes) * self.interval_minutes
        return ts.replace(minute=minute, second=0, microsecond=0)

    def add_tick(self, ts: datetime, ltp: float, day_volume: int) -> Candle | None:
        bucket = self._floor(ts)
        completed = None

        if self.bucket_start is None:
            self.bucket_start = bucket
            self.o = self.h = self.l = self.c = ltp
            self._start_cum_volume = day_volume
            self._last_cum_volume = day_volume
            return None

        if bucket != self.bucket_start:
            vol = max(self._last_cum_volume - self._start_cum_volume, 0)
            completed = Candle(
                timestamp=self.bucket_start, open=self.o, high=self.h, low=self.l,
                close=self.c, volume=vol,
            )
            self.bucket_start = bucket
            self.o = self.h = self.l = self.c = ltp
            self._start_cum_volume = self._last_cum_volume
            self._last_cum_volume = day_volume
        else:
            self.h = max(self.h, ltp)
            self.l = min(self.l, ltp)
            self.c = ltp
            self._last_cum_volume = day_volume

        return completed


@dataclass
class SimPosition:
    side: Side
    entry_time: datetime
    entry_price: float
    qty: int


class PaperTrader:
    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self.tz = pytz.timezone(cfg.market.timezone)
        self.square_off_t = _parse_time(cfg.market.square_off_time)
        self.market_close_t = _parse_time(cfg.market.close_time)

        self.kite = get_kite_client(cfg)
        self.instrument_token = get_instrument_token(self.kite, cfg)

        self.engine = create_strategy_engine(
            cfg.strategy.name, cfg.strategy.params, cfg.instrument.quantity, cfg.market
        )
        self.risk = RiskManager(cfg.risk.max_daily_loss, cfg.risk.kill_switch_file)
        self.engine.set_trade_gate(self.risk.is_trading_allowed)

        self.aggregator = CandleAggregator(interval_minutes=5)
        self.position: SimPosition | None = None
        self.trades: list[Trade] = []

        cfg.logging.log_dir.mkdir(parents=True, exist_ok=True)
        self.signal_log_path = cfg.logging.log_dir / f"signals_{date.today().isoformat()}.csv"
        self._init_signal_log()

        self._stop_event = threading.Event()
        self.ticker: KiteTicker | None = None

    # ---- logging -----------------------------------------------------
    def _init_signal_log(self) -> None:
        is_new = not self.signal_log_path.exists()
        self._signal_log_file = open(self.signal_log_path, "a", newline="")
        self._signal_log_writer = csv.writer(self._signal_log_file)
        if is_new:
            self._signal_log_writer.writerow(
                ["timestamp", "side", "action", "signal_price", "fill_price", "qty", "reason"]
            )

    def _log_signal(self, sig: Signal, fill_price: float) -> None:
        self._signal_log_writer.writerow(
            [sig.timestamp.isoformat(), sig.side.value, sig.action.value,
             f"{sig.price:.2f}", f"{fill_price:.2f}", sig.qty, sig.reason]
        )
        self._signal_log_file.flush()
        logger.info(
            "%s %s %s qty=%d price=%.2f fill=%.2f reason=%s",
            sig.timestamp.strftime("%H:%M:%S"), sig.side.value, sig.action.value,
            sig.qty, sig.price, fill_price, sig.reason,
        )

    # ---- warmup --------------------------------------------------------
    def warmup(self) -> None:
        """Seed VWAP/EMA/volume-average state with recent history so indicators are
        valid as soon as the live session starts."""
        now = datetime.now(self.tz)
        lookback_start = now - timedelta(days=7)
        candles = self.kite.historical_data(
            instrument_token=self.instrument_token,
            from_date=lookback_start,
            to_date=now,
            interval=self.cfg.data.interval,
        )
        today = now.date()
        past_candles = [c for c in candles if c["date"].date() < today]
        warmup_needed = int(self.cfg.strategy.params["volume_avg_period"]) + 5
        for row in past_candles[-warmup_needed:]:
            candle = Candle(
                timestamp=row["date"], open=row["open"], high=row["high"],
                low=row["low"], close=row["close"], volume=row["volume"],
            )
            self.engine.on_candle(candle, warmup=True)
        logger.info("Warmed up indicators with %d prior candles.", min(warmup_needed, len(past_candles)))

    # ---- signal handling -------------------------------------------------
    def _handle_signal(self, sig: Signal) -> None:
        is_buy_fill = (sig.side == Side.LONG) == (sig.action == SignalAction.ENTRY)
        fill_price = costs.apply_slippage(sig.price, is_buy_fill, self.cfg.costs)
        self._log_signal(sig, fill_price)

        if sig.action == SignalAction.ENTRY:
            self.position = SimPosition(
                side=sig.side, entry_time=sig.timestamp, entry_price=fill_price, qty=sig.qty
            )
        else:
            pos = self.position
            assert pos is not None and pos.side == sig.side
            sign = 1 if sig.side == Side.LONG else -1
            gross = (fill_price - pos.entry_price) * pos.qty * sign
            charges = costs.compute_charges(
                pos.entry_price, fill_price, pos.qty, sig.side, self.cfg.costs
            ).total
            trade = Trade(
                side=sig.side, entry_time=pos.entry_time, entry_price=pos.entry_price,
                exit_time=sig.timestamp, exit_price=fill_price, qty=pos.qty,
                exit_reason=sig.reason, gross_pnl=gross, charges=charges,
            )
            self.trades.append(trade)
            self.risk.register_realized_pnl(trade.net_pnl)
            self.position = None
            logger.info(
                "TRADE CLOSED net_pnl=%.2f day_pnl=%.2f reason=%s",
                trade.net_pnl, self.risk.day_pnl, sig.reason,
            )

    def _mark_to_market(self, ltp: float) -> None:
        if self.position is None:
            self.risk.update_unrealized_pnl(0.0)
            return
        sign = 1 if self.position.side == Side.LONG else -1
        unrealized = (ltp - self.position.entry_price) * self.position.qty * sign
        was_halted = self.risk.halted
        self.risk.update_unrealized_pnl(unrealized)
        if self.risk.halted and not was_halted:
            logger.warning("KILL SWITCH TRIGGERED: %s", self.risk.halt_reason)
            self._force_flatten(ltp, "kill_switch")

    def _force_flatten(self, ltp: float, reason: str) -> None:
        sig = self.engine.force_exit(datetime.now(self.tz), ltp, reason)
        if sig is not None:
            self._handle_signal(sig)

    def _on_candle(self, candle: Candle) -> None:
        logger.debug("Candle %s O=%.2f H=%.2f L=%.2f C=%.2f V=%d",
                     candle.timestamp, candle.open, candle.high, candle.low, candle.close, candle.volume)
        for sig in self.engine.on_candle(candle):
            self._handle_signal(sig)

    # ---- ticker callbacks -------------------------------------------------
    def _on_ticks(self, ws, ticks):
        for tick in ticks:
            if tick.get("instrument_token") != self.instrument_token:
                continue
            ts = tick.get("last_trade_time") or datetime.now(self.tz)
            if ts.tzinfo is None:
                ts = self.tz.localize(ts)
            ltp = tick["last_price"]
            day_volume = tick.get("volume_traded", 0)

            self._mark_to_market(ltp)

            completed = self.aggregator.add_tick(ts, ltp, day_volume)
            if completed is not None:
                self._on_candle(completed)

            if ts.time() >= self.market_close_t:
                self._stop_event.set()

    def _on_connect(self, ws, response):
        logger.info("WebSocket connected, subscribing to token %d", self.instrument_token)
        ws.subscribe([self.instrument_token])
        ws.set_mode(ws.MODE_FULL, [self.instrument_token])

    def _on_close(self, ws, code, reason):
        logger.warning("WebSocket closed: %s %s", code, reason)

    def _on_error(self, ws, code, reason):
        logger.error("WebSocket error: %s %s", code, reason)

    # ---- lifecycle -------------------------------------------------------
    def run(self) -> None:
        self.risk.reset_day()
        self.warmup()

        self.ticker = KiteTicker(self.cfg.zerodha.api_key, self.cfg.zerodha.access_token)
        self.ticker.on_ticks = self._on_ticks
        self.ticker.on_connect = self._on_connect
        self.ticker.on_close = self._on_close
        self.ticker.on_error = self._on_error
        self.ticker.connect(threaded=True)

        logger.info("Paper trader running. No real orders will be placed. Ctrl+C to stop.")
        try:
            while not self._stop_event.is_set():
                time_module.sleep(1)
                if self.risk.manual_kill_switch_active() and self.position is not None:
                    logger.warning("Manual kill switch file detected, flattening simulated position.")
                    self._force_flatten(self.position.entry_price, "manual_kill_switch")
        except KeyboardInterrupt:
            logger.info("Interrupted by user.")
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        if self.position is not None:
            logger.warning("Flattening residual open position at shutdown.")
            self._force_flatten(self.position.entry_price, "shutdown_flatten")
        if self.ticker is not None:
            self.ticker.close()
        self._signal_log_file.close()
        logger.info("Session P&L: Rs %.2f across %d trades.", self.risk.day_pnl, len(self.trades))


def main() -> None:
    cfg = load_config()
    cfg.logging.log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, cfg.logging.level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(cfg.logging.log_dir / f"paper_trader_{date.today().isoformat()}.log"),
        ],
    )
    trader = PaperTrader(cfg)
    trader.run()


if __name__ == "__main__":
    main()
