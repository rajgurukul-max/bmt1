"""Typed config loader. Reads config/config.yaml and merges in secrets from .env."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = BASE_DIR / "config" / "config.yaml"

load_dotenv(BASE_DIR / ".env")


@dataclass
class ZerodhaConfig:
    api_key: str
    api_secret: str
    access_token: str


@dataclass
class InstrumentConfig:
    symbol: str
    exchange: str
    quantity: int


@dataclass
class DataConfig:
    interval: str
    history_days: int
    cache_dir: Path
    request_chunk_days: int
    request_pause_seconds: float


@dataclass
class MarketConfig:
    timezone: str
    open_time: str
    close_time: str
    square_off_time: str


@dataclass
class StrategyConfig:
    name: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class CostsConfig:
    brokerage_pct: float
    brokerage_max_per_order: float
    stt_sell_pct: float
    exchange_txn_pct: float
    sebi_charges_pct: float
    stamp_duty_buy_pct: float
    gst_pct: float
    slippage_pct: float


@dataclass
class RiskConfig:
    max_daily_loss: float
    kill_switch_file: Path


@dataclass
class LoggingConfig:
    log_dir: Path
    level: str


@dataclass
class AppConfig:
    zerodha: ZerodhaConfig
    instrument: InstrumentConfig
    data: DataConfig
    market: MarketConfig
    strategy: StrategyConfig
    costs: CostsConfig
    risk: RiskConfig
    logging: LoggingConfig
    raw: dict[str, Any]


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> AppConfig:
    with open(path, "r") as fh:
        raw = yaml.safe_load(fh)

    z = raw["zerodha"]
    zerodha = ZerodhaConfig(
        api_key=os.environ.get(z["api_key_env"], ""),
        api_secret=os.environ.get(z["api_secret_env"], ""),
        access_token=os.environ.get(z["access_token_env"], ""),
    )

    instrument = InstrumentConfig(**raw["instrument"])

    d = raw["data"]
    data = DataConfig(
        interval=d["interval"],
        history_days=d["history_days"],
        cache_dir=BASE_DIR / d["cache_dir"],
        request_chunk_days=d["request_chunk_days"],
        request_pause_seconds=d["request_pause_seconds"],
    )

    market = MarketConfig(**raw["market"])

    active = raw["active_strategy"]
    strategy = StrategyConfig(name=active, params=raw["strategies"][active])

    costs = CostsConfig(**raw["costs"])

    r = raw["risk"]
    risk = RiskConfig(
        max_daily_loss=r["max_daily_loss"],
        kill_switch_file=BASE_DIR / r["kill_switch_file"],
    )

    lg = raw["logging"]
    logging_cfg = LoggingConfig(log_dir=BASE_DIR / lg["log_dir"], level=lg["level"])

    return AppConfig(
        zerodha=zerodha,
        instrument=instrument,
        data=data,
        market=market,
        strategy=strategy,
        costs=costs,
        risk=risk,
        logging=logging_cfg,
        raw=raw,
    )
