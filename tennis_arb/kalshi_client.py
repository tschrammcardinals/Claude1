"""Kalshi REST client.

Kalshi requires every authenticated request to carry an RSA-PSS signature over
`<timestamp_ms><METHOD><path>`, base64-encoded, plus the API key id and the
timestamp in headers. See https://trading-api.readme.io/reference/authentication.
"""
from __future__ import annotations

import base64
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

log = logging.getLogger(__name__)


def load_private_key(path: Path) -> rsa.RSAPrivateKey:
    data = Path(path).read_bytes()
    key = serialization.load_pem_private_key(data, password=None)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise ValueError(f"Expected RSA private key at {path}")
    return key


def _sign(key: rsa.RSAPrivateKey, ts_ms: int, method: str, path: str) -> str:
    msg = f"{ts_ms}{method.upper()}{path}".encode()
    sig = key.sign(
        msg,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH,
        ),
        hashes.SHA256(),
    )
    return base64.b64encode(sig).decode()


class KalshiClient:
    def __init__(
        self,
        api_base: str,
        api_key_id: str,
        private_key_path: Path,
        timeout: float = 10.0,
    ):
        self.api_base = api_base.rstrip("/")
        self.api_key_id = api_key_id
        self._key = load_private_key(private_key_path) if api_key_id else None
        self._client = httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    def _signed_headers(self, method: str, path: str) -> Dict[str, str]:
        if not self._key:
            return {}
        ts = str(int(time.time() * 1000))
        return {
            "KALSHI-ACCESS-KEY": self.api_key_id,
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "KALSHI-ACCESS-SIGNATURE": _sign(self._key, int(ts), method, path),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        authed: bool = True,
    ) -> Dict[str, Any]:
        url = f"{self.api_base}{path}"
        # Signature must cover the path as Kalshi sees it (no query string).
        sig_path = urlparse(url).path
        headers = self._signed_headers(method, sig_path) if authed else {}
        r = await self._client.request(
            method, url, params=params, json=json, headers=headers
        )
        if r.status_code >= 400:
            log.error("kalshi %s %s -> %s %s", method, path, r.status_code, r.text)
        r.raise_for_status()
        return r.json() if r.content else {}

    # ----- Market data -----

    async def list_events(
        self, *, series_ticker: Optional[str] = None, status: str = "open", limit: int = 100
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {"status": status, "limit": limit}
        if series_ticker:
            params["series_ticker"] = series_ticker
        return await self._request("GET", "/events", params=params, authed=False)

    async def list_markets(
        self,
        *,
        event_ticker: Optional[str] = None,
        series_ticker: Optional[str] = None,
        status: str = "open",
        limit: int = 200,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {"status": status, "limit": limit}
        if event_ticker:
            params["event_ticker"] = event_ticker
        if series_ticker:
            params["series_ticker"] = series_ticker
        return await self._request("GET", "/markets", params=params, authed=False)

    async def get_market(self, ticker: str) -> Dict[str, Any]:
        return await self._request("GET", f"/markets/{ticker}", authed=False)

    async def get_orderbook(self, ticker: str, depth: int = 10) -> Dict[str, Any]:
        return await self._request(
            "GET", f"/markets/{ticker}/orderbook", params={"depth": depth}, authed=False
        )

    # ----- Portfolio -----

    async def get_balance(self) -> Dict[str, Any]:
        return await self._request("GET", "/portfolio/balance")

    async def list_positions(self) -> Dict[str, Any]:
        return await self._request("GET", "/portfolio/positions")

    async def list_orders(
        self, *, ticker: Optional[str] = None, status: Optional[str] = None
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if ticker:
            params["ticker"] = ticker
        if status:
            params["status"] = status
        return await self._request("GET", "/portfolio/orders", params=params)

    async def place_order(
        self,
        *,
        ticker: str,
        side: str,           # "yes" or "no"
        action: str,         # "buy" or "sell"
        count: int,
        price_cents: int,    # 1..99
        order_type: str = "limit",
        client_order_id: Optional[str] = None,
        post_only: bool = True,
    ) -> Dict[str, Any]:
        body = {
            "ticker": ticker,
            "side": side,
            "action": action,
            "count": count,
            "type": order_type,
            "client_order_id": client_order_id or str(uuid.uuid4()),
            "post_only": post_only,
        }
        if order_type == "limit":
            # Kalshi expects yes_price for yes-side, no_price for no-side, in cents.
            body["yes_price" if side == "yes" else "no_price"] = price_cents
        return await self._request("POST", "/portfolio/orders", json=body)

    async def cancel_order(self, order_id: str) -> Dict[str, Any]:
        return await self._request("DELETE", f"/portfolio/orders/{order_id}")
