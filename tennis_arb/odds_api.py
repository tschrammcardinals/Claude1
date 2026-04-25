"""Optional sportsbook anchor via the-odds-api.com.

Strongly recommended: the sportsbook line IS what the Kalshi market converges
to in this strategy, so reading it directly is more reliable than predicting
it. If no API key is configured, this returns None and the trader falls back
to the Elo model alone.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

import httpx

log = logging.getLogger(__name__)

BASE = "https://api.the-odds-api.com/v4"


class OddsAPI:
    def __init__(self, api_key: str, *, region: str = "us", timeout: float = 10.0):
        self.api_key = api_key
        self.region = region
        self._client = httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def list_tennis_events(self, sport_key: str = "tennis_atp") -> List[Dict]:
        r = await self._client.get(
            f"{BASE}/sports/{sport_key}/odds",
            params={
                "apiKey": self.api_key,
                "regions": self.region,
                "markets": "h2h",
                "oddsFormat": "decimal",
            },
        )
        r.raise_for_status()
        return r.json()

    @staticmethod
    def implied_prob(decimal_odds: float) -> float:
        return 1.0 / decimal_odds if decimal_odds > 0 else 0.5

    @staticmethod
    def fair_prob(price_a: float, price_b: float) -> float:
        """De-vig two-way odds; returns implied prob for player A."""
        ia = 1.0 / price_a
        ib = 1.0 / price_b
        return ia / (ia + ib)

    async def fair_for_pair(
        self, name_a: str, name_b: str, *, sport_key: str = "tennis_atp"
    ) -> Optional[float]:
        """Returns devigged P(A wins) using the average of available books, or None."""
        events = await self.list_tennis_events(sport_key)
        target = {name_a.lower(), name_b.lower()}
        for ev in events:
            participants = {ev.get("home_team", "").lower(), ev.get("away_team", "").lower()}
            if not target.issubset(participants):
                continue
            probs_a, probs_b = [], []
            for book in ev.get("bookmakers", []):
                for mkt in book.get("markets", []):
                    if mkt.get("key") != "h2h":
                        continue
                    by_name = {o["name"].lower(): o["price"] for o in mkt.get("outcomes", [])}
                    if name_a.lower() in by_name and name_b.lower() in by_name:
                        p = self.fair_prob(by_name[name_a.lower()], by_name[name_b.lower()])
                        probs_a.append(p)
                        probs_b.append(1 - p)
            if probs_a:
                return sum(probs_a) / len(probs_a)
        return None
