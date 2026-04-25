"""Exposure caps, daily loss kill switch, and a file-flag panic stop."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

from .config import RiskConfig
from .store import Store

log = logging.getLogger(__name__)

KILLSWITCH_PATH = Path(".killswitch")


@dataclass
class MarketExposure:
    yes_contracts: int = 0
    no_contracts: int = 0
    cost_basis_usd: float = 0.0


class RiskManager:
    def __init__(self, cfg: RiskConfig, store: Store):
        self.cfg = cfg
        self.store = store
        self._exposure: Dict[str, MarketExposure] = {}

    def killswitch_tripped(self) -> bool:
        if KILLSWITCH_PATH.exists():
            log.warning("killswitch file present; halting new orders")
            return True
        if self.store.realised_pnl_today() <= -self.cfg.max_daily_loss:
            log.warning("daily loss cap hit; halting new orders")
            return True
        return False

    def _market(self, ticker: str) -> MarketExposure:
        return self._exposure.setdefault(ticker, MarketExposure())

    def total_exposure_usd(self) -> float:
        return sum(e.cost_basis_usd for e in self._exposure.values())

    def can_place(
        self, ticker: str, side: str, count: int, price_cents: int
    ) -> tuple[bool, str]:
        if self.killswitch_tripped():
            return False, "killswitch"

        notional = count * price_cents / 100.0
        e = self._market(ticker)
        side_count = e.yes_contracts if side == "yes" else e.no_contracts

        if side_count + count > self.cfg.max_contracts_per_side:
            return False, "per-side contract cap"

        if e.cost_basis_usd + notional > self.cfg.max_exposure_per_market:
            return False, "per-market exposure cap"

        if self.total_exposure_usd() + notional > self.cfg.max_global_exposure:
            return False, "global exposure cap"

        return True, "ok"

    def record_fill(
        self, ticker: str, side: str, count: int, price_cents: int, action: str
    ) -> None:
        e = self._market(ticker)
        notional = count * price_cents / 100.0
        sign = 1 if action == "buy" else -1
        if side == "yes":
            e.yes_contracts += sign * count
        else:
            e.no_contracts += sign * count
        e.cost_basis_usd = max(0.0, e.cost_basis_usd + sign * notional)
