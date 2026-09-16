"""Zerodha-style intraday equity transaction cost model, plus slippage.

All figures are approximations of Zerodha's published intraday equity charges as of
2024-2025 and are fully configurable via config/config.yaml so they can be kept in
sync with future rate changes.
"""
from __future__ import annotations

from dataclasses import dataclass

from config import CostsConfig
from models import Side


@dataclass
class ChargeBreakdown:
    brokerage: float
    stt: float
    exchange_txn_charges: float
    sebi_charges: float
    stamp_duty: float
    gst: float

    @property
    def total(self) -> float:
        return (
            self.brokerage
            + self.stt
            + self.exchange_txn_charges
            + self.sebi_charges
            + self.stamp_duty
            + self.gst
        )


def apply_slippage(price: float, is_buy: bool, cfg: CostsConfig) -> float:
    """Return the realistic fill price after adverse slippage.

    Buys fill worse (higher), sells fill worse (lower) — slippage always works
    against the trader.
    """
    factor = cfg.slippage_pct / 100.0
    return price * (1 + factor) if is_buy else price * (1 - factor)


def compute_charges(
    entry_price: float, exit_price: float, qty: int, side: Side, cfg: CostsConfig
) -> ChargeBreakdown:
    """Round-trip charges for one intraday trade of `qty` shares."""
    buy_price, sell_price = (
        (entry_price, exit_price) if side == Side.LONG else (exit_price, entry_price)
    )
    buy_turnover = buy_price * qty
    sell_turnover = sell_price * qty
    total_turnover = buy_turnover + sell_turnover

    brokerage_leg = lambda turnover: min(  # noqa: E731
        turnover * cfg.brokerage_pct / 100.0, cfg.brokerage_max_per_order
    )
    brokerage = brokerage_leg(buy_turnover) + brokerage_leg(sell_turnover)

    stt = sell_turnover * cfg.stt_sell_pct / 100.0
    exchange_txn_charges = total_turnover * cfg.exchange_txn_pct / 100.0
    sebi_charges = total_turnover * cfg.sebi_charges_pct / 100.0
    stamp_duty = buy_turnover * cfg.stamp_duty_buy_pct / 100.0
    gst = (brokerage + exchange_txn_charges + sebi_charges) * cfg.gst_pct / 100.0

    return ChargeBreakdown(
        brokerage=brokerage,
        stt=stt,
        exchange_txn_charges=exchange_txn_charges,
        sebi_charges=sebi_charges,
        stamp_duty=stamp_duty,
        gst=gst,
    )
