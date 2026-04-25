from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from .elo import EloModel

log = logging.getLogger(__name__)


class Predictor:
    """Loads trained Elo models for ATP and/or WTA and gives win probabilities."""

    def __init__(self, atp: Optional[EloModel] = None, wta: Optional[EloModel] = None):
        self.atp = atp
        self.wta = wta

    @classmethod
    def from_artifacts(cls, artifacts_dir: Path) -> "Predictor":
        def maybe(p: Path) -> Optional[EloModel]:
            return EloModel.from_dict(json.loads(p.read_text())) if p.exists() else None

        atp = maybe(artifacts_dir / "elo_atp.json")
        wta = maybe(artifacts_dir / "elo_wta.json")
        if atp is None and wta is None:
            log.warning(
                "no Elo artifacts found in %s; predictor will return 0.5 for all matches",
                artifacts_dir,
            )
        return cls(atp=atp, wta=wta)

    def _pick(self, tour: Optional[str]) -> Optional[EloModel]:
        if tour and tour.lower() == "atp":
            return self.atp
        if tour and tour.lower() == "wta":
            return self.wta
        return self.atp or self.wta

    def prob(
        self,
        player_a: str,
        player_b: str,
        *,
        surface: str = "Hard",
        tour: Optional[str] = None,
    ) -> float:
        m = self._pick(tour)
        if m is None:
            return 0.5
        # If neither player exists in ratings, fall back to 0.5.
        if player_a not in m.players and player_b not in m.players:
            return 0.5
        return m.prob(player_a, player_b, surface)

    def fair_price_cents(
        self,
        player_a: str,
        player_b: str,
        *,
        surface: str = "Hard",
        tour: Optional[str] = None,
    ) -> int:
        p = self.prob(player_a, player_b, surface=surface, tour=tour)
        return max(1, min(99, round(p * 100)))
