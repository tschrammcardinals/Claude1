"""Surface-aware Elo for tennis.

Each player carries an overall rating plus a per-surface rating (Hard, Clay,
Grass, Carpet). Predictions use a blend: combined = alpha*surface + (1-alpha)*overall.
This is the same formula tennis-data sites like Tennis Abstract use; values
calibrate well against real win probabilities for ATP/WTA tour matches.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Iterable

SURFACES = ("Hard", "Clay", "Grass", "Carpet")


@dataclass
class PlayerRating:
    overall: float = 1500.0
    surface: Dict[str, float] = field(default_factory=lambda: {s: 1500.0 for s in SURFACES})
    matches: int = 0
    surface_matches: Dict[str, int] = field(default_factory=lambda: {s: 0 for s in SURFACES})


def _expected(rating_a: float, rating_b: float) -> float:
    return 1.0 / (1.0 + math.pow(10.0, (rating_b - rating_a) / 400.0))


def _k(matches: int, base_k: float) -> float:
    # Higher K early on to converge fast, then stable.
    return base_k * 250.0 / (matches + 100.0) if matches < 100 else base_k * 0.7


class EloModel:
    def __init__(
        self,
        *,
        surface_alpha: float = 0.65,
        k_factor: float = 32.0,
        default_rating: float = 1500.0,
    ):
        self.surface_alpha = surface_alpha
        self.k_factor = k_factor
        self.default_rating = default_rating
        self.players: Dict[str, PlayerRating] = {}

    def _get(self, name: str) -> PlayerRating:
        if name not in self.players:
            self.players[name] = PlayerRating(
                overall=self.default_rating,
                surface={s: self.default_rating for s in SURFACES},
                surface_matches={s: 0 for s in SURFACES},
            )
        return self.players[name]

    def combined(self, name: str, surface: str) -> float:
        p = self._get(name)
        s = surface if surface in SURFACES else "Hard"
        return self.surface_alpha * p.surface[s] + (1.0 - self.surface_alpha) * p.overall

    def prob(self, player_a: str, player_b: str, surface: str) -> float:
        return _expected(
            self.combined(player_a, surface), self.combined(player_b, surface)
        )

    def update(self, winner: str, loser: str, surface: str) -> None:
        s = surface if surface in SURFACES else "Hard"
        w, l = self._get(winner), self._get(loser)

        # Overall update.
        exp_w = _expected(w.overall, l.overall)
        kw = _k(w.matches, self.k_factor)
        kl = _k(l.matches, self.k_factor)
        w.overall += kw * (1 - exp_w)
        l.overall += kl * (0 - (1 - exp_w))

        # Surface update.
        exp_ws = _expected(w.surface[s], l.surface[s])
        kws = _k(w.surface_matches[s], self.k_factor)
        kls = _k(l.surface_matches[s], self.k_factor)
        w.surface[s] += kws * (1 - exp_ws)
        l.surface[s] += kls * (0 - (1 - exp_ws))

        w.matches += 1
        l.matches += 1
        w.surface_matches[s] += 1
        l.surface_matches[s] += 1

    def to_dict(self) -> dict:
        return {
            "surface_alpha": self.surface_alpha,
            "k_factor": self.k_factor,
            "default_rating": self.default_rating,
            "players": {
                n: {
                    "overall": p.overall,
                    "surface": p.surface,
                    "matches": p.matches,
                    "surface_matches": p.surface_matches,
                }
                for n, p in self.players.items()
            },
        }

    @classmethod
    def from_dict(cls, d: dict) -> "EloModel":
        m = cls(
            surface_alpha=d.get("surface_alpha", 0.65),
            k_factor=d.get("k_factor", 32.0),
            default_rating=d.get("default_rating", 1500.0),
        )
        for name, p in d.get("players", {}).items():
            m.players[name] = PlayerRating(
                overall=p["overall"],
                surface=p["surface"],
                matches=p["matches"],
                surface_matches=p["surface_matches"],
            )
        return m

    def train(self, matches: Iterable[tuple[str, str, str]]) -> None:
        for winner, loser, surface in matches:
            self.update(winner, loser, surface)
