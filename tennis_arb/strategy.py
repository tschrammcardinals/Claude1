"""Pricing logic.

For each side (Yes / No) we want a maker-maker round trip:
    buy at B, later sell at S
where B < fair < S and (S - B) - maker_fee(B) - maker_fee(S) >= target_net_cents.

We pick B and S to be as close to fair as possible while clearing the after-fee
target — that maximises fill probability for a given target edge. If the
configured offsets don't clear the target, the optimizer widens them until
they do (or returns None if no legal price meets the target).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from .config import StrategyConfig
from .fees import FeeModel

log = logging.getLogger(__name__)


@dataclass
class OrderbookTouch:
    yes_bid: Optional[int] = None
    yes_ask: Optional[int] = None
    no_bid: Optional[int] = None
    no_ask: Optional[int] = None


def parse_orderbook(ob: dict) -> OrderbookTouch:
    """Best bid/ask from a Kalshi orderbook payload.

    Kalshi's `/markets/{ticker}/orderbook` returns yes/no books each as an
    array of `[price_cents, size]` pairs. Yes bids are sorted descending and
    asks ascending; the no book mirrors it.
    """
    body = ob.get("orderbook", ob) or {}
    yes = body.get("yes") or []
    no = body.get("no") or []

    def _best(levels: list, side: str) -> Optional[int]:
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


@dataclass
class SideQuote:
    """Optimised entry-bid and exit-ask for one side of a market."""
    bid: int
    ask: int
    expected_net_per_contract: float


class Strategy:
    def __init__(self, cfg: StrategyConfig, fees: FeeModel):
        self.cfg = cfg
        self.fees = fees

    def _optimise_side(
        self, fair_cents: int, max_bid: Optional[int], min_ask: Optional[int]
    ) -> Optional[SideQuote]:
        """Find (B, S) closest to fair such that:
            (S - B) - maker_fee(B) - maker_fee(S) >= target_net_per_contract
        """
        target = self.cfg.target_net_per_contract_cents

        # Start at the configured offsets and widen until the target clears.
        bid = fair_cents - self.cfg.bid_offset_cents
        ask = fair_cents + self.cfg.ask_offset_cents

        # Cap bid below the current ask (post-only safety) and ask above the bid.
        if min_ask is not None:
            bid = min(bid, min_ask - 1)
        if max_bid is not None:
            ask = max(ask, max_bid + 1)

        for _ in range(20):
            if bid < 1 or ask > 99 or bid >= ask:
                return None
            net = self.fees.net_round_trip_cents_per_contract(bid, ask)
            if net >= target:
                return SideQuote(bid=bid, ask=ask, expected_net_per_contract=net)
            # Widen by 1c on whichever side is cheaper to widen (closer to 50c
            # has higher fees, so push the cheaper-fee leg).
            if abs(bid - 50) < abs(ask - 50):
                bid -= 1
            else:
                ask += 1
        return None

    def quotes(
        self, fair_yes_cents: int, ob: OrderbookTouch
    ) -> tuple[Optional[SideQuote], Optional[SideQuote]]:
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
            return None, None

        yes = self._optimise_side(fair_yes_cents, ob.yes_bid, ob.yes_ask)
        no = self._optimise_side(100 - fair_yes_cents, ob.no_bid, ob.no_ask)
        return yes, no

    def initial_bids(
        self, fair_yes_cents: int, ob: OrderbookTouch, count: int
    ) -> list[TradeIntent]:
        yes, no = self.quotes(fair_yes_cents, ob)
        intents: list[TradeIntent] = []
        if yes:
            log.info(
                "yes quote: bid=%dc ask=%dc net=%.2fc/contract",
                yes.bid, yes.ask, yes.expected_net_per_contract,
            )
            intents.append(TradeIntent("yes", "buy", yes.bid, count))
        if no:
            log.info(
                "no quote: bid=%dc ask=%dc net=%.2fc/contract",
                no.bid, no.ask, no.expected_net_per_contract,
            )
            intents.append(TradeIntent("no", "buy", no.bid, count))
        return intents

    def exit_ask(
        self, side: str, fair_yes_cents: int, ob: OrderbookTouch
    ) -> Optional[TradeIntent]:
        yes, no = self.quotes(fair_yes_cents, ob)
        q = yes if side == "yes" else no
        if not q:
            return None
        return TradeIntent(side, "sell", q.ask, count=0)
