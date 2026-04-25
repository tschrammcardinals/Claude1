"""Train Elo on Sackmann ATP/WTA data and write artifacts/elo_<tour>.json.

Usage:
    python -m scripts.train_model --tour atp --years 2015-2024
    python -m scripts.train_model --tour wta --years 2018-2024
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from tennis_arb.config import load_config
from tennis_arb.model.train import train_tour


def parse_years(spec: str) -> list[int]:
    if "-" in spec:
        a, b = spec.split("-", 1)
        return list(range(int(a), int(b) + 1))
    return [int(y) for y in spec.split(",")]


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--tour", choices=["atp", "wta"], required=True)
    p.add_argument("--years", default="2015-2024", help="e.g. 2015-2024 or 2020,2021,2022")
    p.add_argument("--config", default="config.yaml")
    args = p.parse_args()

    cfg = load_config(args.config)
    out = train_tour(
        args.tour,
        parse_years(args.years),
        Path(cfg.artifacts_dir),
        surface_alpha=cfg.model.surface_alpha,
        k_factor=cfg.model.k_factor,
        default_rating=cfg.model.default_rating,
    )
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
