"""Quick sanity check: load config + model, predict a couple of matchups.

Usage:
    python -m scripts.dry_run "Carlos Alcaraz" "Jannik Sinner" --surface Hard --tour atp
"""
from __future__ import annotations

import argparse
import logging

from tennis_arb.config import load_config
from tennis_arb.model.predict import Predictor


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    p = argparse.ArgumentParser()
    p.add_argument("player_a")
    p.add_argument("player_b")
    p.add_argument("--surface", default="Hard")
    p.add_argument("--tour", choices=["atp", "wta"], default=None)
    p.add_argument("--config", default="config.yaml")
    args = p.parse_args()

    cfg = load_config(args.config)
    pred = Predictor.from_artifacts(cfg.artifacts_dir)
    p_a = pred.prob(args.player_a, args.player_b, surface=args.surface, tour=args.tour)
    print(f"P({args.player_a} beats {args.player_b} on {args.surface}) = {p_a:.3f}")
    print(f"Implied YES fair price: {round(p_a*100)}c")
    print(f"Implied NO fair price:  {100 - round(p_a*100)}c")


if __name__ == "__main__":
    main()
