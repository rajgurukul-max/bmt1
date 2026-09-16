"""Daily hard-loss limit and manual kill switch.

Shared by backtest.py (so the simulation reflects the same discipline that will be
enforced live) and paper_trader.py.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class RiskManager:
    def __init__(self, max_daily_loss: float, kill_switch_file: Path):
        self.max_daily_loss = max_daily_loss
        self.kill_switch_file = kill_switch_file
        self._realized_pnl = 0.0
        self._unrealized_pnl = 0.0
        self._halted = False
        self._halt_reason = ""

    def reset_day(self) -> None:
        self._realized_pnl = 0.0
        self._unrealized_pnl = 0.0
        self._halted = False
        self._halt_reason = ""

    def register_realized_pnl(self, pnl: float) -> None:
        self._realized_pnl += pnl
        self._check_loss_limit()

    def update_unrealized_pnl(self, pnl: float) -> None:
        self._unrealized_pnl = pnl
        self._check_loss_limit()

    @property
    def day_pnl(self) -> float:
        return self._realized_pnl + self._unrealized_pnl

    def _check_loss_limit(self) -> None:
        if not self._halted and self.day_pnl <= -abs(self.max_daily_loss):
            self._halted = True
            self._halt_reason = (
                f"Daily max loss breached: pnl={self.day_pnl:.2f} "
                f"<= -{abs(self.max_daily_loss):.2f}"
            )
            logger.warning(self._halt_reason)

    def manual_kill_switch_active(self) -> bool:
        return self.kill_switch_file.exists()

    def is_trading_allowed(self) -> bool:
        if self._halted:
            return False
        if self.manual_kill_switch_active():
            if not self._halted:
                self._halt_reason = f"Manual kill switch file present: {self.kill_switch_file}"
                logger.warning(self._halt_reason)
            self._halted = True
            return False
        return True

    @property
    def halted(self) -> bool:
        return self._halted or self.manual_kill_switch_active()

    @property
    def halt_reason(self) -> str:
        return self._halt_reason
