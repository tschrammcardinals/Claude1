"""Kalshi fee model.

Per Kalshi's published fee schedule (Feb 2026):

  taker_fee_dollars  = ceil_to_cent( 0.0700 * C * p * (1 - p) )
  maker_fee_dollars  = ceil_to_cent( 0.0175 * C * p * (1 - p) )

where C = contracts and p = price in dollars (0.00..1.00). Maker fees are 25%
of taker fees.

Our strategy uses post-only limit orders so we are makers on entry and exit;
the optimizer assumes maker fees by default. If a market goes against us and
we have to sweep with a marketable order, the fee is taker.

Sources:
  https://kalshi.com/fee-schedule
  https://kalshi.com/docs/kalshi-fee-schedule.pdf
"""
from __future__ import annotations

import math
from dataclasses import dataclass


def _ceil_cents(dollars: float) -> int:
    return math.ceil(dollars * 100 - 1e-12)


@dataclass
class FeeModel:
    maker_rate: float = 0.0175
    taker_rate: float = 0.0700

    def maker_fee_cents(self, count: int, price_cents: int) -> int:
        p = price_cents / 100.0
        return _ceil_cents(self.maker_rate * count * p * (1.0 - p))

    def taker_fee_cents(self, count: int, price_cents: int) -> int:
        p = price_cents / 100.0
        return _ceil_cents(self.taker_rate * count * p * (1.0 - p))

    def round_trip_maker_cents(
        self, count: int, buy_price_cents: int, sell_price_cents: int
    ) -> int:
        return self.maker_fee_cents(count, buy_price_cents) + self.maker_fee_cents(
            count, sell_price_cents
        )

    def net_round_trip_cents_per_contract(
        self, buy_price_cents: int, sell_price_cents: int, count: int = 100
    ) -> float:
        """Profit per contract, in cents, on a maker-maker round trip after fees.

        Uses count=100 for fee-rounding granularity (1 contract round-up
        distorts the per-contract cost; at 100 contracts the per-contract fee
        is essentially the unrounded value).
        """
        gross = (sell_price_cents - buy_price_cents) * count
        fees = self.round_trip_maker_cents(count, buy_price_cents, sell_price_cents)
        return (gross - fees) / count
