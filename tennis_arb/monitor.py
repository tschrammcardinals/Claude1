"""Detect freshly-listed Kalshi tennis markets.

Strategy:
  1. Poll /events filtered by configured series tickers (or all open events).
  2. For each event matching tennis keywords, list its markets.
  3. Yield any market we haven't seen before.

Once a market is known, the trader subscribes to its orderbook over WS for
millisecond reactions. The monitor itself only handles *discovery*.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import AsyncIterator, Optional

from .config import MonitorConfig
from .kalshi_client import KalshiClient
from .store import Store

log = logging.getLogger(__name__)


@dataclass
class NewMarket:
    ticker: str
    event_ticker: str
    title: str
    subtitle: str
    yes_sub_title: Optional[str]
    no_sub_title: Optional[str]
    close_time: Optional[str]
    payload: dict


def _is_tennis_event(ev: dict, keywords: list[str]) -> bool:
    text = " ".join(
        str(ev.get(k, ""))
        for k in ("title", "sub_title", "category", "series_ticker")
    ).lower()
    return any(k.lower() in text for k in keywords)


class MarketMonitor:
    def __init__(self, client: KalshiClient, store: Store, cfg: MonitorConfig):
        self.client = client
        self.store = store
        self.cfg = cfg

    async def _scan_once(self) -> list[NewMarket]:
        events: list[dict] = []
        if self.cfg.series_tickers:
            for series in self.cfg.series_tickers:
                try:
                    page = await self.client.list_events(series_ticker=series)
                except Exception as e:
                    log.warning("list_events(%s) failed: %s", series, e)
                    continue
                events.extend(page.get("events", []))
        else:
            try:
                page = await self.client.list_events()
            except Exception as e:
                log.warning("list_events() failed: %s", e)
                return []
            events.extend(
                ev for ev in page.get("events", [])
                if _is_tennis_event(ev, self.cfg.title_keywords)
            )

        new: list[NewMarket] = []
        for ev in events:
            ev_ticker = ev.get("event_ticker") or ev.get("ticker")
            if not ev_ticker:
                continue
            try:
                mkts_page = await self.client.list_markets(event_ticker=ev_ticker)
            except Exception as e:
                log.warning("list_markets(%s) failed: %s", ev_ticker, e)
                continue
            for m in mkts_page.get("markets", []):
                ticker = m.get("ticker")
                if not ticker or self.store.is_known_market(ticker):
                    continue
                self.store.remember_market(ticker, m)
                new.append(
                    NewMarket(
                        ticker=ticker,
                        event_ticker=ev_ticker,
                        title=m.get("title") or ev.get("title", ""),
                        subtitle=m.get("subtitle") or ev.get("sub_title", ""),
                        yes_sub_title=m.get("yes_sub_title"),
                        no_sub_title=m.get("no_sub_title"),
                        close_time=m.get("close_time"),
                        payload=m,
                    )
                )
        return new

    async def stream(self) -> AsyncIterator[NewMarket]:
        while True:
            try:
                for nm in await self._scan_once():
                    yield nm
            except Exception:
                log.exception("scan failed; continuing")
            await asyncio.sleep(self.cfg.poll_interval_seconds)
