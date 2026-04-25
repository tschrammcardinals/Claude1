"""Order execution + market lifecycle.

For each detected tennis market the Trader:
  1. Computes fair price from the model (or sportsbook anchor if available).
  2. Places resting Yes and No bids below fair.
  3. Subscribes to the orderbook over WS, refreshes bids if the touch moves.
  4. When filled, places an ask above fair. Repeats until cutoff before match.
  5. At cutoff, cancels open orders. (Position liquidation is a separate task —
     for v1 we leave residual exposure; see TODO at the bottom.)
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from dateutil import parser as dtparser

from .config import AppConfig
from .kalshi_client import KalshiClient
from .model.predict import Predictor
from .monitor import NewMarket
from .name_match import parse_title, resolve_pair
from .odds_api import OddsAPI
from .risk import RiskManager
from .store import Store
from .strategy import Strategy, TradeIntent, parse_orderbook

log = logging.getLogger(__name__)

PAPER_LOG = Path("paper_orders.jsonl")


@dataclass
class MarketSession:
    market: NewMarket
    fair_yes_cents: int
    cutoff_utc: Optional[datetime]


class Trader:
    def __init__(
        self,
        cfg: AppConfig,
        client: KalshiClient,
        store: Store,
        predictor: Predictor,
        risk: RiskManager,
        odds: Optional[OddsAPI] = None,
    ):
        self.cfg = cfg
        self.client = client
        self.store = store
        self.predictor = predictor
        self.risk = risk
        self.odds = odds
        self.strategy = Strategy(cfg.strategy)

    @property
    def live(self) -> bool:
        return self.cfg.kalshi.live

    async def _fair_price_cents(self, nm: NewMarket) -> Optional[int]:
        """Pull a fair price for the YES side. Sportsbook anchor if we have one,
        else the Elo model. Returns None if neither source can price the match."""
        title = nm.title or ""
        parsed = parse_title(title) or parse_title(nm.subtitle or "")
        # Player names from yes_sub_title can be cleaner ("Carlos Alcaraz") than
        # the full title.
        if not parsed and nm.yes_sub_title and nm.no_sub_title:
            parsed = (nm.yes_sub_title, nm.no_sub_title)
        if not parsed:
            log.info("can't parse players from %r", title)
            return None
        raw_a, raw_b = parsed

        # Surface guess from event title (Kalshi sometimes encodes it).
        surface = "Hard"
        for s in ("Clay", "Grass", "Carpet"):
            if s.lower() in (title + nm.subtitle).lower():
                surface = s
                break

        # Tour guess from series ticker / title.
        tour = "atp" if "atp" in (nm.event_ticker or "").lower() or "atp" in title.lower() else (
            "wta" if "wta" in (nm.event_ticker or "").lower() or "wta" in title.lower() else None
        )

        # Try sportsbook anchor first.
        if self.odds:
            try:
                p = await self.odds.fair_for_pair(
                    raw_a, raw_b, sport_key=f"tennis_{tour or 'atp'}"
                )
                if p is not None:
                    return max(1, min(99, round(p * 100)))
            except Exception as e:
                log.warning("odds api lookup failed (%s); falling back to model", e)

        # Map raw names to Sackmann names from our trained model.
        m = self.predictor.atp if tour == "atp" else (
            self.predictor.wta if tour == "wta" else (self.predictor.atp or self.predictor.wta)
        )
        candidates = list(m.players.keys()) if m else []
        a, b = resolve_pair(raw_a, raw_b, candidates)
        if not (a and b):
            log.info("name match failed: %r / %r -> %r / %r", raw_a, raw_b, a, b)
            return None
        return self.predictor.fair_price_cents(a, b, surface=surface, tour=tour)

    def _cutoff(self, nm: NewMarket) -> Optional[datetime]:
        if not nm.close_time:
            return None
        try:
            close = dtparser.parse(nm.close_time)
            if close.tzinfo is None:
                close = close.replace(tzinfo=timezone.utc)
            return close - timedelta(minutes=self.cfg.strategy.cutoff_minutes_before_start)
        except Exception:
            return None

    async def _place(self, ticker: str, intent: TradeIntent) -> None:
        ok, reason = self.risk.can_place(
            ticker, intent.side, intent.count, intent.price_cents
        )
        if not ok:
            log.info("[risk] skip %s %s %d@%dc: %s", ticker, intent.side, intent.count, intent.price_cents, reason)
            return

        coid = f"arb-{uuid.uuid4().hex[:12]}"
        if not self.live:
            row = {
                "ts": datetime.utcnow().isoformat(),
                "ticker": ticker,
                "side": intent.side,
                "action": intent.action,
                "count": intent.count,
                "price_cents": intent.price_cents,
                "client_order_id": coid,
            }
            with PAPER_LOG.open("a") as f:
                f.write(json.dumps(row) + "\n")
            log.info("[PAPER] %s %s %s %d@%dc", ticker, intent.action, intent.side, intent.count, intent.price_cents)
            self.store.record_order(
                client_order_id=coid,
                ticker=ticker,
                side=intent.side,
                action=intent.action,
                count=intent.count,
                price_cents=intent.price_cents,
                status="paper",
                paper=True,
            )
            return

        try:
            resp = await self.client.place_order(
                ticker=ticker,
                side=intent.side,
                action=intent.action,
                count=intent.count,
                price_cents=intent.price_cents,
                client_order_id=coid,
                post_only=True,
            )
            server_id = (resp.get("order") or {}).get("order_id") or resp.get("order_id")
            log.info(
                "[LIVE] %s %s %s %d@%dc -> %s",
                ticker, intent.action, intent.side, intent.count, intent.price_cents, server_id,
            )
            self.store.record_order(
                client_order_id=coid,
                ticker=ticker,
                side=intent.side,
                action=intent.action,
                count=intent.count,
                price_cents=intent.price_cents,
                status="placed",
                paper=False,
                server_id=server_id,
            )
        except Exception:
            log.exception("place_order failed for %s", ticker)

    async def handle_new_market(self, nm: NewMarket, *, count: int = 10) -> None:
        fair = await self._fair_price_cents(nm)
        if fair is None:
            log.info("no fair price for %s; skipping", nm.ticker)
            return

        try:
            ob_raw = await self.client.get_orderbook(nm.ticker)
        except Exception as e:
            log.warning("orderbook fetch failed for %s: %s", nm.ticker, e)
            ob_raw = {}
        ob = parse_orderbook(ob_raw)

        log.info(
            "new market %s | fair=%dc | yes_bid=%s yes_ask=%s | %s",
            nm.ticker, fair, ob.yes_bid, ob.yes_ask, nm.title,
        )
        for intent in self.strategy.initial_bids(fair, ob, count=count):
            await self._place(nm.ticker, intent)

    # ----- Lifecycle: refresh bids + place exit asks until cutoff -----

    async def manage_market(self, nm: NewMarket, *, count: int = 10) -> None:
        cutoff = self._cutoff(nm)
        await self.handle_new_market(nm, count=count)

        while True:
            if cutoff and datetime.now(timezone.utc) >= cutoff:
                log.info("cutoff reached for %s; stopping", nm.ticker)
                return
            if self.risk.killswitch_tripped():
                return
            await asyncio.sleep(5)

            # Re-pull fair (sportsbook may have moved) so exit asks track it.
            fair = await self._fair_price_cents(nm)
            if fair is None:
                continue

            # Place exit asks for any positions we now hold above fair.
            exp = self.risk._exposure.get(nm.ticker)
            if exp:
                if exp.yes_contracts > 0:
                    ask = self.strategy.exit_ask("yes", fair)
                    if ask:
                        ask.count = exp.yes_contracts
                        await self._place(nm.ticker, ask)
                if exp.no_contracts > 0:
                    ask = self.strategy.exit_ask("no", fair)
                    if ask:
                        ask.count = exp.no_contracts
                        await self._place(nm.ticker, ask)

# TODO(v2):
#   - Subscribe to WS orderbook deltas instead of polling get_orderbook.
#   - Cancel + replace bids when the touch moves > N cents.
#   - At cutoff, sweep remaining position via marketable orders to flatten.
#   - Listen to fill events to drive risk.record_fill in real time.
