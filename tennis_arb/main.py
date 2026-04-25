"""Orchestrator: discover tennis markets and dispatch a Trader for each."""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
from pathlib import Path

from .config import load_config
from .kalshi_client import KalshiClient
from .model.predict import Predictor
from .monitor import MarketMonitor
from .odds_api import OddsAPI
from .risk import RiskManager
from .store import Store
from .trader import Trader

log = logging.getLogger(__name__)


def _setup_logging() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


async def run(live_flag: bool, config_path: str) -> None:
    cfg = load_config(config_path)

    if live_flag and not cfg.kalshi.live:
        raise SystemExit(
            "--live passed but KALSHI_LIVE != true in env. Both are required."
        )
    if cfg.kalshi.live and not live_flag:
        log.warning("KALSHI_LIVE=true but --live not passed; staying in PAPER mode")
        cfg.kalshi.live = False

    log.info("mode = %s", "LIVE" if cfg.kalshi.live else "PAPER")

    client = KalshiClient(
        api_base=cfg.kalshi.api_base,
        api_key_id=cfg.kalshi.api_key_id,
        private_key_path=cfg.kalshi.private_key_path,
    )
    store = Store(Path(cfg.artifacts_dir) / "state.sqlite")
    predictor = Predictor.from_artifacts(cfg.artifacts_dir)
    risk = RiskManager(cfg.risk, store)
    odds = (
        OddsAPI(cfg.odds_api_key, cache_seconds=cfg.odds_api_cache_seconds)
        if cfg.odds_api_key
        else None
    )

    monitor = MarketMonitor(client, store, cfg.monitor)
    trader = Trader(cfg, client, store, predictor, risk, odds=odds)

    pending: set[asyncio.Task] = set()
    try:
        async for nm in monitor.stream():
            log.info("==> new market %s | %s", nm.ticker, nm.title)
            t = asyncio.create_task(trader.manage_market(nm))
            pending.add(t)
            t.add_done_callback(pending.discard)
    finally:
        for t in pending:
            t.cancel()
        await client.aclose()
        if odds:
            await odds.aclose()


def main() -> None:
    _setup_logging()
    p = argparse.ArgumentParser()
    p.add_argument("--live", action="store_true", help="enable live order placement")
    p.add_argument("--config", default="config.yaml")
    args = p.parse_args()
    try:
        asyncio.run(run(args.live, args.config))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
