"""SQLite-backed state for known markets, open orders, and daily P&L."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Iterator, Optional


SCHEMA = """
CREATE TABLE IF NOT EXISTS known_markets (
    ticker TEXT PRIMARY KEY,
    first_seen_utc TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    client_order_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,
    action TEXT NOT NULL,
    count INTEGER NOT NULL,
    price_cents INTEGER NOT NULL,
    status TEXT NOT NULL,
    placed_utc TEXT NOT NULL,
    paper INTEGER NOT NULL DEFAULT 0,
    server_id TEXT
);
CREATE TABLE IF NOT EXISTS daily_pnl (
    day TEXT PRIMARY KEY,
    realised_usd REAL NOT NULL DEFAULT 0,
    fees_usd REAL NOT NULL DEFAULT 0
);
"""


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def is_known_market(self, ticker: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM known_markets WHERE ticker = ?", (ticker,)
        )
        return cur.fetchone() is not None

    def remember_market(self, ticker: str, payload: dict) -> None:
        with self.tx() as c:
            c.execute(
                "INSERT OR IGNORE INTO known_markets(ticker, first_seen_utc, payload) VALUES (?, ?, ?)",
                (ticker, datetime.utcnow().isoformat(), json.dumps(payload)),
            )

    def record_order(
        self,
        *,
        client_order_id: str,
        ticker: str,
        side: str,
        action: str,
        count: int,
        price_cents: int,
        status: str,
        paper: bool,
        server_id: Optional[str] = None,
    ) -> None:
        with self.tx() as c:
            c.execute(
                """INSERT OR REPLACE INTO orders
                   (client_order_id, ticker, side, action, count, price_cents,
                    status, placed_utc, paper, server_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    client_order_id,
                    ticker,
                    side,
                    action,
                    count,
                    price_cents,
                    status,
                    datetime.utcnow().isoformat(),
                    1 if paper else 0,
                    server_id,
                ),
            )

    def add_realised_pnl(self, amount_usd: float, fees_usd: float = 0.0) -> None:
        today = date.today().isoformat()
        with self.tx() as c:
            c.execute(
                "INSERT OR IGNORE INTO daily_pnl(day, realised_usd, fees_usd) VALUES (?, 0, 0)",
                (today,),
            )
            c.execute(
                "UPDATE daily_pnl SET realised_usd = realised_usd + ?, fees_usd = fees_usd + ? WHERE day = ?",
                (amount_usd, fees_usd, today),
            )

    def realised_pnl_today(self) -> float:
        today = date.today().isoformat()
        cur = self._conn.execute(
            "SELECT realised_usd, fees_usd FROM daily_pnl WHERE day = ?", (today,)
        )
        row = cur.fetchone()
        if not row:
            return 0.0
        return float(row["realised_usd"]) - float(row["fees_usd"])
