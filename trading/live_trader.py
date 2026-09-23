"""Live intraday trading via Kite Ticker -- PLACES REAL ORDERS.

Streams real-time ticks for the configured symbol, builds 5-minute candles,
feeds the same strategy engine used by backtest.py/paper_trader.py, and on
every ENTRY/EXIT signal places a real LIMIT order (with a small price buffer
for near-immediate fill -- Kite rejects MARKET orders without market
protection) via kite.place_order. This is the live counterpart of
paper_trader.py, which deliberately never places orders; this script is the
one that does.

Safety features:
  - Refuses to start if it finds an existing non-zero net position in the
    configured symbol (could be a leftover from a crashed prior run) --
    resolve that manually first rather than risk double-counting it.
  - Daily max-loss kill switch (risk.py) force-flattens and stops taking new
    entries for the rest of the day.
  - Manual kill switch file (touch KILL_SWITCH) is polled and also flattens.
  - Catches SIGTERM as well as Ctrl+C/SIGINT so a normal `kill` (not -9)
    still runs the shutdown/flatten path, not just Ctrl+C.
  - `--dry-run` logs every order it *would* place without calling
    kite.place_order at all -- run this first to sanity-check a fresh config
    before trusting it with real orders.

Usage:
    python live_trader.py              # places real orders
    python live_trader.py --dry-run    # logs intended orders only, no live calls

Standing practice for this project: always launch with
    nohup python live_trader.py > logs/live_trader_out.log 2>&1 & disown
so an SSH disconnect can't kill the process out from under an open position.
"""
from __future__ import annotations

import argparse
import csv
import logging
import signal
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

logger = logging.getLogger("live_trader")

ORDER_POLL_INTERVAL_S = 1.0
ORDER_FILL_TIMEOUT_S = 30.0
LIMIT_PRICE_BUFFER = 0.10  # rupees, added/subtracted from LTP for near-immediate fill


def _parse_time(value: str) -> time:
    hh, mm = value.split(":")
    return time(int(hh), int(mm))


class CandleAggregator:
    """Buckets ticks into completed 5-minute OHLCV candles. Identical to the one
    in paper_trader.py -- kept as its own copy so this file has no dependency on
    the no-orders simulator."""

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
class LivePosition:
    side: Side
    entry_time: datetime
    entry_price: float  # actual average fill price
    qty: int


class LiveTrader:
    def __init__(self, cfg: AppConfig, dry_run: bool):
        self.cfg = cfg
        self.dry_run = dry_run
        self.tz = pytz.timezone(cfg.market.timezone)
        self.square_off_t = _parse_time(cfg.market.square_off_time)
        self.market_close_t = _parse_time(cfg.market.close_time)

        self.kite = get_kite_client(cfg)
        self.instrument_token = get_instrument_token(self.kite, cfg)
        self.tradingsymbol = cfg.instrument.symbol
        self.exchange = cfg.instrument.exchange

        self.engine = create_strategy_engine(
            cfg.strategy.name, cfg.strategy.params, cfg.instrument.quantity, cfg.market
        )
        self.risk = RiskManager(cfg.risk.max_daily_loss, cfg.risk.kill_switch_file)
        self.engine.set_trade_gate(self.risk.is_trading_allowed)

        self.aggregator = CandleAggregator(interval_minutes=5)
        self.position: LivePosition | None = None
        self.trades: list[Trade] = []

        cfg.logging.log_dir.mkdir(parents=True, exist_ok=True)
        self.signal_log_path = cfg.logging.log_dir / f"live_signals_{date.today().isoformat()}.csv"
        self._init_signal_log()

        self._stop_event = threading.Event()
        self.ticker: KiteTicker | None = None

    # ---- startup safety check ------------------------------------------
    def check_no_existing_position(self) -> None:
        positions = self.kite.positions()["net"]
        for p in positions:
            if p["tradingsymbol"] == self.tradingsymbol and p["exchange"] == self.exchange and p["quantity"] != 0:
                raise RuntimeError(
                    f"Found an existing open position in {self.tradingsymbol} "
                    f"(qty={p['quantity']}, avg_price={p['average_price']}) before this "
                    f"run even started. Refusing to start -- resolve/flatten it manually "
                    f"first (or confirm it's intentional and adapt this script), otherwise "
                    f"a fresh strategy signal here could double up on it."
                )
        logger.info("Startup check OK: no existing open position in %s.", self.tradingsymbol)

    # ---- logging ---------------------------------------------------------
    def _init_signal_log(self) -> None:
        is_new = not self.signal_log_path.exists()
        self._signal_log_file = open(self.signal_log_path, "a", newline="")
        self._signal_log_writer = csv.writer(self._signal_log_file)
        if is_new:
            self._signal_log_writer.writerow(
                ["timestamp", "side", "action", "signal_price", "fill_price", "qty", "reason", "order_id"]
            )
            self._signal_log_file.flush()

    def _log_signal(self, sig: Signal, fill_price: float, order_id: str | None) -> None:
        self._signal_log_writer.writerow(
            [sig.timestamp.isoformat(), sig.side.value, sig.action.value,
             f"{sig.price:.2f}", f"{fill_price:.2f}", sig.qty, sig.reason, order_id or ""]
        )
        self._signal_log_file.flush()
        logger.info(
            "%s %s %s qty=%d signal_price=%.2f fill=%.2f reason=%s order_id=%s",
            sig.timestamp.strftime("%H:%M:%S"), sig.side.value, sig.action.value,
            sig.qty, sig.price, fill_price, sig.reason, order_id,
        )

    # ---- warmup ------------------------------------------------------------
    def warmup(self) -> None:
        """Feed the last few trading days of candles through the engine with
        warmup=True so Supertrend/RSI/Bollinger/pivot-R1 are all primed before
        the live session starts. Pivot R1 specifically needs at least one full
        prior trading day, so this feeds several calendar days back, not just
        a handful of bars."""
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
        for row in past_candles:
            candle = Candle(
                timestamp=row["date"], open=row["open"], high=row["high"],
                low=row["low"], close=row["close"], volume=row["volume"],
            )
            self.engine.on_candle(candle, warmup=True)
        logger.info("Warmed up indicators with %d prior candles.", len(past_candles))

    # ---- order placement ---------------------------------------------------
    def _place_limit_order(self, side: Side, action: SignalAction, qty: int, ltp: float) -> tuple[str | None, float]:
        """Place a LIMIT order with a small buffer for near-immediate fill (Kite
        rejects bare MARKET orders without market protection), poll until it's
        COMPLETE, and return (order_id, actual_average_fill_price).
        In --dry-run mode, logs what it would have done and returns a synthetic
        fill at the buffered limit price instead of calling the API."""
        is_buy = (side == Side.LONG) == (action == SignalAction.ENTRY)
        limit_price = round(ltp + LIMIT_PRICE_BUFFER, 1) if is_buy else round(ltp - LIMIT_PRICE_BUFFER, 1)
        transaction_type = self.kite.TRANSACTION_TYPE_BUY if is_buy else self.kite.TRANSACTION_TYPE_SELL

        if self.dry_run:
            logger.warning(
                "[DRY RUN] Would place %s %s qty=%d limit=%.2f (ltp=%.2f)",
                transaction_type, self.tradingsymbol, qty, limit_price, ltp,
            )
            return None, limit_price

        order_id = self.kite.place_order(
            variety=self.kite.VARIETY_REGULAR,
            exchange=self.exchange,
            tradingsymbol=self.tradingsymbol,
            transaction_type=transaction_type,
            quantity=qty,
            product=self.kite.PRODUCT_MIS,
            order_type=self.kite.ORDER_TYPE_LIMIT,
            price=limit_price,
        )
        logger.info("Placed order_id=%s %s qty=%d limit=%.2f", order_id, transaction_type, qty, limit_price)

        deadline = time_module.monotonic() + ORDER_FILL_TIMEOUT_S
        while time_module.monotonic() < deadline:
            history = self.kite.order_history(order_id)
            last = history[-1]
            status = last["status"]
            if status == "COMPLETE":
                avg_price = float(last["average_price"])
                logger.info("Order %s COMPLETE avg_price=%.2f", order_id, avg_price)
                return order_id, avg_price
            if status in ("REJECTED", "CANCELLED"):
                raise RuntimeError(f"Order {order_id} ended in status={status}: {last.get('status_message')}")
            time_module.sleep(ORDER_POLL_INTERVAL_S)

        logger.error("Order %s did not fill within %.0fs -- cancelling and raising.", order_id, ORDER_FILL_TIMEOUT_S)
        try:
            self.kite.cancel_order(variety=self.kite.VARIETY_REGULAR, order_id=order_id)
        finally:
            raise RuntimeError(f"Order {order_id} failed to fill in time; cancelled, manual check needed.")

    # ---- signal handling -------------------------------------------------
    def _handle_signal(self, sig: Signal) -> None:
        order_id, fill_price = self._place_limit_order(sig.side, sig.action, sig.qty, sig.price)
        self._log_signal(sig, fill_price, order_id)

        if sig.action == SignalAction.ENTRY:
            self.position = LivePosition(
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
        self.check_no_existing_position()
        self.risk.reset_day()
        self.warmup()

        self.ticker = KiteTicker(self.cfg.zerodha.api_key, self.cfg.zerodha.access_token)
        self.ticker.on_ticks = self._on_ticks
        self.ticker.on_connect = self._on_connect
        self.ticker.on_close = self._on_close
        self.ticker.on_error = self._on_error
        self.ticker.connect(threaded=True)

        mode = "DRY RUN (no real orders)" if self.dry_run else "LIVE (placing real orders)"
        logger.info("Live trader running in %s mode. Ctrl+C or SIGTERM to stop.", mode)

        def _handle_term(signum, frame):
            self._stop_event.set()
        signal.signal(signal.SIGTERM, _handle_term)

        try:
            while not self._stop_event.is_set():
                time_module.sleep(1)
                if self.risk.manual_kill_switch_active() and self.position is not None:
                    logger.warning("Manual kill switch file detected, flattening open position.")
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Log intended orders without placing them.")
    args = parser.parse_args()

    cfg = load_config()
    cfg.logging.log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, cfg.logging.level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(cfg.logging.log_dir / f"live_trader_{date.today().isoformat()}.log"),
        ],
    )
    trader = LiveTrader(cfg, dry_run=args.dry_run)
    trader.run()


if __name__ == "__main__":
    main()
