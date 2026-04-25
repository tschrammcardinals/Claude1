"""Kalshi WebSocket client for orderbook deltas and ticker updates."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import AsyncIterator, Iterable

import websockets
from cryptography.hazmat.primitives.asymmetric import rsa

from .kalshi_client import _sign, load_private_key

log = logging.getLogger(__name__)


class KalshiWS:
    def __init__(
        self,
        ws_base: str,
        api_key_id: str,
        private_key_path: Path,
    ):
        self.ws_base = ws_base
        self.api_key_id = api_key_id
        self._key: rsa.RSAPrivateKey | None = (
            load_private_key(private_key_path) if api_key_id else None
        )
        self._next_id = 1

    def _auth_headers(self) -> list[tuple[str, str]]:
        if not self._key:
            return []
        ts = str(int(time.time() * 1000))
        # WS auth signs the path "/trade-api/ws/v2".
        path = "/trade-api/ws/v2"
        return [
            ("KALSHI-ACCESS-KEY", self.api_key_id),
            ("KALSHI-ACCESS-TIMESTAMP", ts),
            ("KALSHI-ACCESS-SIGNATURE", _sign(self._key, int(ts), "GET", path)),
        ]

    async def stream(
        self, channels: Iterable[str], market_tickers: Iterable[str]
    ) -> AsyncIterator[dict]:
        """Subscribe to channels for a set of tickers; yield messages forever.

        Reconnects with exponential backoff on transport errors.
        """
        backoff = 1.0
        tickers = list(market_tickers)
        chans = list(channels)
        while True:
            try:
                async with websockets.connect(
                    self.ws_base,
                    additional_headers=self._auth_headers(),
                    ping_interval=20,
                ) as ws:
                    sub = {
                        "id": self._next_id,
                        "cmd": "subscribe",
                        "params": {"channels": chans, "market_tickers": tickers},
                    }
                    self._next_id += 1
                    await ws.send(json.dumps(sub))
                    backoff = 1.0
                    async for raw in ws:
                        try:
                            yield json.loads(raw)
                        except json.JSONDecodeError:
                            log.warning("kalshi ws non-json frame: %r", raw[:200])
            except (websockets.ConnectionClosed, OSError) as e:
                log.warning("kalshi ws disconnected (%s); reconnect in %.1fs", e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
