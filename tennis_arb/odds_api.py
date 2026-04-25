"""Optional sportsbook anchor via the-odds-api.com.

The sportsbook line IS what the Kalshi market converges to in this strategy,
so reading it directly is more reliable than predicting it. If no API key
is configured, this returns None and the trader falls back to the Elo model
alone.

A single `/sports/{sport}/odds` call returns odds for *every* current event
in that sport — so we cache the response and serve all match-ups out of the
cache for `cache_seconds`. That keeps the free tier (500 req/mo) viable: at
the default 300s TTL during active tennis hours you'd use ~12 req/hour, well
under the cap.
"""
from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional, Tuple

import httpx

log = logging.getLogger(__name__)

BASE = "https://api.the-odds-api.com/v4"


class OddsAPI:
    def __init__(
        self,
        api_key: str,
        *,
        region: str = "us",
        timeout: float = 10.0,
        cache_seconds: int = 300,
    ):
        self.api_key = api_key
        self.region = region
        self.cache_seconds = cache_seconds
        self._client = httpx.AsyncClient(timeout=timeout)
        self._cache: Dict[str, Tuple[float, List[Dict]]] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    async def list_tennis_events(self, sport_key: str = "tennis_atp") -> List[Dict]:
        cached = self._cache.get(sport_key)
        if cached and (time.time() - cached[0]) < self.cache_seconds:
            return cached[1]
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
        events = r.json()
        self._cache[sport_key] = (time.time(), events)
        # Surface the rate-limit headers for visibility.
        remaining = r.headers.get("x-requests-remaining")
        used = r.headers.get("x-requests-used")
        if remaining is not None:
            log.info("the-odds-api: %s remaining / %s used", remaining, used)
        return events

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
