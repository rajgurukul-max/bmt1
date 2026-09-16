"""Download and locally cache historical 5-minute candles for the configured symbol.

Usage:
    python data.py                # update the cache with the latest 12 months
    python data.py --refresh-all  # ignore the cache and re-download everything
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from kiteconnect import KiteConnect

from config import AppConfig, load_config

logger = logging.getLogger(__name__)

INSTRUMENTS_CACHE_TTL = timedelta(days=1)


def get_kite_client(cfg: AppConfig) -> KiteConnect:
    if not cfg.zerodha.api_key or not cfg.zerodha.access_token:
        raise RuntimeError(
            "KITE_API_KEY / KITE_ACCESS_TOKEN not set. Copy .env.example to .env, "
            "fill in your API key, and run `python auth.py` to generate today's "
            "access token."
        )
    kite = KiteConnect(api_key=cfg.zerodha.api_key)
    kite.set_access_token(cfg.zerodha.access_token)
    return kite


def _instruments_cache_path(cfg: AppConfig) -> Path:
    return cfg.data.cache_dir / f"instruments_{cfg.instrument.exchange}.json"


def get_instrument_token(kite: KiteConnect, cfg: AppConfig) -> int:
    cfg.data.cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = _instruments_cache_path(cfg)

    instruments = None
    if cache_path.exists():
        age = datetime.now() - datetime.fromtimestamp(cache_path.stat().st_mtime)
        if age < INSTRUMENTS_CACHE_TTL:
            with open(cache_path) as fh:
                instruments = json.load(fh)

    if instruments is None:
        logger.info("Refreshing instrument dump for %s", cfg.instrument.exchange)
        instruments = kite.instruments(cfg.instrument.exchange)
        with open(cache_path, "w") as fh:
            json.dump(instruments, fh)

    for inst in instruments:
        if (
            inst["tradingsymbol"] == cfg.instrument.symbol
            and inst["exchange"] == cfg.instrument.exchange
        ):
            return int(inst["instrument_token"])

    raise ValueError(
        f"Instrument {cfg.instrument.symbol} not found on {cfg.instrument.exchange}"
    )


def _candle_cache_path(cfg: AppConfig) -> Path:
    cfg.data.cache_dir.mkdir(parents=True, exist_ok=True)
    return (
        cfg.data.cache_dir
        / f"{cfg.instrument.symbol}_{cfg.instrument.exchange}_{cfg.data.interval}.csv"
    )


def load_cached_candles(cfg: AppConfig) -> pd.DataFrame:
    path = _candle_cache_path(cfg)
    if not path.exists():
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
    df = pd.read_csv(path, parse_dates=["date"])
    df["date"] = pd.to_datetime(df["date"], utc=True).dt.tz_convert(cfg.market.timezone)
    return df.sort_values("date").reset_index(drop=True)


def save_cached_candles(cfg: AppConfig, df: pd.DataFrame) -> None:
    path = _candle_cache_path(cfg)
    df.sort_values("date").drop_duplicates(subset="date").to_csv(path, index=False)


def _download_range(
    kite: KiteConnect, token: int, from_dt: datetime, to_dt: datetime, cfg: AppConfig
) -> pd.DataFrame:
    """Download historical candles in chunks respecting Kite's per-request day cap."""
    chunks: list[pd.DataFrame] = []
    chunk_start = from_dt
    step = timedelta(days=cfg.data.request_chunk_days)

    while chunk_start < to_dt:
        chunk_end = min(chunk_start + step, to_dt)
        logger.info("Fetching %s -> %s", chunk_start.date(), chunk_end.date())
        try:
            candles = kite.historical_data(
                instrument_token=token,
                from_date=chunk_start,
                to_date=chunk_end,
                interval=cfg.data.interval,
            )
        except Exception:
            logger.exception("Historical data fetch failed for %s -> %s", chunk_start, chunk_end)
            raise
        if candles:
            chunks.append(pd.DataFrame(candles))
        time.sleep(cfg.data.request_pause_seconds)
        chunk_start = chunk_end

    if not chunks:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

    df = pd.concat(chunks, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"]).dt.tz_convert(cfg.market.timezone)
    return df[["date", "open", "high", "low", "close", "volume"]]


def update_cache(cfg: AppConfig, refresh_all: bool = False) -> pd.DataFrame:
    kite = get_kite_client(cfg)
    token = get_instrument_token(kite, cfg)

    now = datetime.now()
    earliest_wanted = now - timedelta(days=cfg.data.history_days)

    existing = pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
    from_dt = earliest_wanted

    if not refresh_all:
        existing = load_cached_candles(cfg)
        if not existing.empty:
            last_cached = existing["date"].max().to_pydatetime().replace(tzinfo=None)
            from_dt = max(earliest_wanted, last_cached + timedelta(minutes=1))

    if from_dt >= now:
        logger.info("Cache already up to date.")
        return existing

    fresh = _download_range(kite, token, from_dt, now, cfg)
    combined = pd.concat([existing, fresh], ignore_index=True)
    combined = combined.sort_values("date").drop_duplicates(subset="date").reset_index(drop=True)
    save_cached_candles(cfg, combined)
    logger.info("Cache now holds %d candles (%s -> %s)", len(combined), combined["date"].min(), combined["date"].max())
    return combined


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh-all", action="store_true")
    args = parser.parse_args()

    cfg = load_config()
    update_cache(cfg, refresh_all=args.refresh_all)


if __name__ == "__main__":
    main()
