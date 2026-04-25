"""Pricing logic. Decides bid/ask prices given a model fair price and the
current orderbook snapshot.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from .config import StrategyConfig

log = logging.getLogger(__name__)


@dataclass
class OrderbookTouch:
    yes_bid: Optional[int] = None  # cents
    yes_ask: Optional[int] = None
    no_bid: Optional[int] = None
    no_ask: Optional[int] = None


def parse_orderbook(ob: dict) -> OrderbookTouch:
    """Extract best bid/ask from a Kalshi orderbook payload.

    Kalshi returns yes/no order books each as a list of [price_cents, size]
    pairs sorted by price. Yes bids are descending, asks ascending.
    """
    body = ob.get("orderbook", ob) or {}
    yes = body.get("yes") or []
    no = body.get("no") or []

    def _best(levels: list, side: str) -> Optional[int]:
        if not levels:
            return None
        prices = [int(lvl[0]) for lvl in levels if lvl and lvl[0] is not None]
        if not prices:
            return None
        return max(prices) if side == "bid" else min(prices)

    return OrderbookTouch(
        yes_bid=_best(yes, "bid"),
        yes_ask=_best(yes, "ask"),
        no_bid=_best(no, "bid"),
        no_ask=_best(no, "ask"),
    )


@dataclass
class TradeIntent:
    side: str       # "yes" or "no"
    action: str     # "buy" or "sell"
    price_cents: int
    count: int


class Strategy:
    def __init__(self, cfg: StrategyConfig):
        self.cfg = cfg

    def initial_bids(
        self, fair_yes_cents: int, ob: OrderbookTouch, count: int
    ) -> list[TradeIntent]:
        """Place resting bids on both Yes and No sides below fair.

        For a Yes/No binary market, P(yes) + P(no) = 1, so fair_no = 100 - fair_yes.
        We want to *buy* below fair on each side and later sell above fair.
        """
        if not (
            self.cfg.min_fair_price_cents
            <= fair_yes_cents
            <= self.cfg.max_fair_price_cents
        ):
            log.info(
                "skip: fair %dc outside trading band [%d, %d]",
                fair_yes_cents,
                self.cfg.min_fair_price_cents,
                self.cfg.max_fair_price_cents,
            )
            return []

        fair_no_cents = 100 - fair_yes_cents
        intents: list[TradeIntent] = []

        yes_bid = fair_yes_cents - self.cfg.edge_cents
        if ob.yes_bid is not None:
            yes_bid = min(yes_bid, ob.yes_bid + self.cfg.initial_bid_offset_cents)
        if 1 <= yes_bid <= 99:
            intents.append(TradeIntent("yes", "buy", yes_bid, count))

        no_bid = fair_no_cents - self.cfg.edge_cents
        if ob.no_bid is not None:
            no_bid = min(no_bid, ob.no_bid + self.cfg.initial_bid_offset_cents)
        if 1 <= no_bid <= 99:
            intents.append(TradeIntent("no", "buy", no_bid, count))

        return intents

    def exit_ask(self, side: str, fair_yes_cents: int) -> Optional[TradeIntent]:
        """Once we hold contracts, list a resting sell above fair."""
        fair = fair_yes_cents if side == "yes" else 100 - fair_yes_cents
        ask = fair + self.cfg.ask_offset_cents
        if not (1 <= ask <= 99):
            return None
        return TradeIntent(side, "sell", ask, count=0)  # caller fills count
