"""Loader for Jeff Sackmann's tennis match CSVs.

Repos:
  - ATP: https://github.com/JeffSackmann/tennis_atp
  - WTA: https://github.com/JeffSackmann/tennis_wta

Files of interest: atp_matches_YYYY.csv, wta_matches_YYYY.csv. Columns we use:
tourney_date, surface, winner_name, loser_name.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable, List, Tuple

import httpx
import pandas as pd

log = logging.getLogger(__name__)

ATP_BASE = "https://raw.githubusercontent.com/JeffSackmann/tennis_atp/master"
WTA_BASE = "https://raw.githubusercontent.com/JeffSackmann/tennis_wta/master"


def _csv_url(tour: str, year: int) -> str:
    base = ATP_BASE if tour == "atp" else WTA_BASE
    return f"{base}/{tour}_matches_{year}.csv"


def download_year(tour: str, year: int, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / f"{tour}_matches_{year}.csv"
    if out.exists():
        return out
    url = _csv_url(tour, year)
    log.info("downloading %s", url)
    r = httpx.get(url, timeout=30.0, follow_redirects=True)
    r.raise_for_status()
    out.write_bytes(r.content)
    return out


def load_matches(
    tour: str, years: Iterable[int], dest_dir: Path
) -> List[Tuple[str, str, str, pd.Timestamp]]:
    """Returns chronologically-sorted (winner, loser, surface, date) tuples."""
    frames = []
    for y in years:
        path = download_year(tour, y, dest_dir)
        df = pd.read_csv(path, low_memory=False)
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)

    df = df.dropna(subset=["winner_name", "loser_name", "surface", "tourney_date"])
    df["tourney_date"] = pd.to_datetime(df["tourney_date"], format="%Y%m%d", errors="coerce")
    df = df.dropna(subset=["tourney_date"]).sort_values("tourney_date")

    return list(
        zip(
            df["winner_name"].astype(str),
            df["loser_name"].astype(str),
            df["surface"].astype(str),
            df["tourney_date"],
        )
    )
