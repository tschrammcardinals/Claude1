from __future__ import annotations

import os
from pathlib import Path
from typing import List

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field


class StrategyConfig(BaseModel):
    edge_cents: int = 4
    ask_offset_cents: int = 3
    initial_bid_offset_cents: int = 2
    cutoff_minutes_before_start: int = 5
    min_fair_price_cents: int = 15
    max_fair_price_cents: int = 85


class RiskConfig(BaseModel):
    max_exposure_per_market: float = 50.0
    max_contracts_per_side: int = 100
    max_daily_loss: float = 500.0
    max_global_exposure: float = 2000.0


class MonitorConfig(BaseModel):
    poll_interval_seconds: float = 2.0
    series_tickers: List[str] = Field(default_factory=list)
    title_keywords: List[str] = Field(default_factory=lambda: ["tennis", "atp", "wta"])


class ModelConfig(BaseModel):
    surface_alpha: float = 0.65
    k_factor: float = 32.0
    default_rating: float = 1500.0
    recency_half_life_days: int = 730


class KalshiCreds(BaseModel):
    api_key_id: str
    private_key_path: Path
    api_base: str
    ws_base: str
    live: bool = False


class AppConfig(BaseModel):
    strategy: StrategyConfig
    risk: RiskConfig
    monitor: MonitorConfig
    model: ModelConfig
    kalshi: KalshiCreds
    odds_api_key: str | None = None
    artifacts_dir: Path = Path("./artifacts")


def load_config(yaml_path: str | Path = "config.yaml") -> AppConfig:
    load_dotenv()

    raw = yaml.safe_load(Path(yaml_path).read_text()) or {}

    kalshi = KalshiCreds(
        api_key_id=os.environ.get("KALSHI_API_KEY_ID", ""),
        private_key_path=Path(os.environ.get("KALSHI_PRIVATE_KEY_PATH", "")),
        api_base=os.environ.get(
            "KALSHI_API_BASE", "https://api.elections.kalshi.com/trade-api/v2"
        ),
        ws_base=os.environ.get(
            "KALSHI_WS_BASE", "wss://api.elections.kalshi.com/trade-api/ws/v2"
        ),
        live=os.environ.get("KALSHI_LIVE", "false").lower() == "true",
    )

    return AppConfig(
        strategy=StrategyConfig(**raw.get("strategy", {})),
        risk=RiskConfig(**raw.get("risk", {})),
        monitor=MonitorConfig(**raw.get("monitor", {})),
        model=ModelConfig(**raw.get("model", {})),
        kalshi=kalshi,
        odds_api_key=os.environ.get("ODDS_API_KEY") or None,
        artifacts_dir=Path(os.environ.get("ARTIFACTS_DIR", "./artifacts")),
    )
