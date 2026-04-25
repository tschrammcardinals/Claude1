from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Iterable

from .data import load_all_matches
from .elo import EloModel

log = logging.getLogger(__name__)


def train_tour(
    tour: str,
    years: Iterable[int],
    artifacts_dir: Path,
    *,
    surface_alpha: float = 0.65,
    k_factor: float = 32.0,
    default_rating: float = 1500.0,
) -> Path:
    data_dir = artifacts_dir / "data"
    matches = load_all_matches(tour, years, data_dir)
    log.info("loaded %d %s matches", len(matches), tour)

    model = EloModel(
        surface_alpha=surface_alpha,
        k_factor=k_factor,
        default_rating=default_rating,
    )
    for winner, loser, surface, _ in matches:
        model.update(winner, loser, surface)

    artifacts_dir.mkdir(parents=True, exist_ok=True)
    out = artifacts_dir / f"elo_{tour}.json"
    out.write_text(json.dumps(model.to_dict()))
    log.info("wrote %s (%d players)", out, len(model.players))
    return out
