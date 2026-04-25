"""Loaders for two tennis match-history sources.

  - Sackmann (Jeff Sackmann, github.com/JeffSackmann/tennis_atp & tennis_wta)
    Canonical form, well-cleaned, but year-end CSVs lag the season —
    typically published after the year completes.

  - Tennis-Data (tennis-data.co.uk) Updated weekly through the current week.
    Uses an abbreviated name form ("Lastname F.") that we normalize back to
    the Sackmann full-name form so a single player keeps a single Elo rating
    across both sources.

The combined `load_all_matches` returns chronologically-sorted
`(winner, loser, surface, date)` tuples spanning both sources.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Iterable, List, Tuple

import httpx
import pandas as pd

log = logging.getLogger(__name__)

ATP_BASE = "https://raw.githubusercontent.com/JeffSackmann/tennis_atp/master"
WTA_BASE = "https://raw.githubusercontent.com/JeffSackmann/tennis_wta/master"
TD_BASE = "http://www.tennis-data.co.uk"


# ---------- Sackmann ----------

def _sack_url(tour: str, year: int) -> str:
    base = ATP_BASE if tour == "atp" else WTA_BASE
    return f"{base}/{tour}_matches_{year}.csv"


def download_sackmann(tour: str, year: int, dest_dir: Path) -> Path | None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / f"{tour}_matches_{year}.csv"
    if out.exists():
        return out
    url = _sack_url(tour, year)
    r = httpx.get(url, timeout=30.0, follow_redirects=True)
    if r.status_code == 404:
        log.info("Sackmann %s not yet published (404)", url)
        return None
    r.raise_for_status()
    out.write_bytes(r.content)
    return out


def load_sackmann(
    tour: str, years: Iterable[int], dest_dir: Path
) -> List[Tuple[str, str, str, pd.Timestamp]]:
    frames = []
    for y in years:
        path = download_sackmann(tour, y, dest_dir)
        if path is None:
            continue
        frames.append(pd.read_csv(path, low_memory=False))
    if not frames:
        return []
    df = pd.concat(frames, ignore_index=True)
    df = df.dropna(subset=["winner_name", "loser_name", "surface", "tourney_date"])
    df["tourney_date"] = pd.to_datetime(df["tourney_date"], format="%Y%m%d", errors="coerce")
    df = df.dropna(subset=["tourney_date"]).sort_values("tourney_date")
    return list(zip(
        df["winner_name"].astype(str),
        df["loser_name"].astype(str),
        df["surface"].astype(str),
        df["tourney_date"],
    ))


# ---------- Tennis-Data (weekly, current) ----------

def _td_url(tour: str, year: int) -> str:
    suffix = "" if tour == "atp" else "w"
    return f"{TD_BASE}/{year}{suffix}/{year}.xlsx"


def download_tennis_data(tour: str, year: int, dest_dir: Path) -> Path | None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / f"{tour}_td_{year}.xlsx"
    if out.exists():
        return out
    url = _td_url(tour, year)
    r = httpx.get(url, timeout=30.0, follow_redirects=True)
    if r.status_code == 404:
        log.info("tennis-data %s not yet published (404)", url)
        return None
    r.raise_for_status()
    out.write_bytes(r.content)
    return out


_NORM_RE = re.compile(r"[^\w\s]")


def _norm_token(s: str) -> str:
    return _NORM_RE.sub("", s.replace("-", " ")).strip().lower()


def _td_split(td_name: str) -> tuple[str, str] | None:
    """Tennis-Data 'Lastname[ Lastname2] X.' -> (lastname_norm, initial)."""
    parts = [p for p in td_name.replace(".", "").split() if p]
    if len(parts) < 2:
        return None
    initial = parts[-1][0].upper()
    last = " ".join(parts[:-1])
    return _norm_token(last), initial


def _sack_split(sack_name: str) -> tuple[str, str] | None:
    """Sackmann 'Firstname Lastname[ Lastname2]' -> (lastname_norm, initial)."""
    parts = [p for p in sack_name.split() if p]
    if len(parts) < 2:
        return None
    first = parts[0]
    last = " ".join(parts[1:])
    return _norm_token(last), first[0].upper()


def build_td_to_sackmann_map(sackmann_names: Iterable[str]) -> dict[tuple[str, str], str]:
    out: dict[tuple[str, str], str] = {}
    for full in sackmann_names:
        key = _sack_split(full)
        if key:
            out[key] = full
    return out


def normalize_td_name(td_name: str, lookup: dict[tuple[str, str], str]) -> str:
    key = _td_split(td_name)
    if key is None:
        return td_name
    return lookup.get(key, td_name)


def load_tennis_data(
    tour: str,
    years: Iterable[int],
    dest_dir: Path,
    name_lookup: dict[tuple[str, str], str] | None = None,
) -> List[Tuple[str, str, str, pd.Timestamp]]:
    frames = []
    for y in years:
        path = download_tennis_data(tour, y, dest_dir)
        if path is None:
            continue
        frames.append(pd.read_excel(path))
    if not frames:
        return []
    df = pd.concat(frames, ignore_index=True)
    df = df.dropna(subset=["Winner", "Loser", "Surface", "Date"])
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"]).sort_values("Date")

    lookup = name_lookup or {}
    return [
        (
            normalize_td_name(str(w), lookup),
            normalize_td_name(str(l), lookup),
            str(s),
            d,
        )
        for w, l, s, d in zip(df["Winner"], df["Loser"], df["Surface"], df["Date"])
    ]


# ---------- Combined ----------

def load_all_matches(
    tour: str, years: Iterable[int], dest_dir: Path
) -> List[Tuple[str, str, str, pd.Timestamp]]:
    """Sackmann for years it has published, tennis-data for years it doesn't.

    Names from tennis-data are normalized to Sackmann's full-name form using
    a (surname, first-initial) lookup against the Sackmann player set. New
    players that don't appear in Sackmann keep their tennis-data form.
    """
    years = sorted(set(years))
    sack = load_sackmann(tour, years, dest_dir)
    sack_names = {w for w, _, _, _ in sack} | {l for _, l, _, _ in sack}
    lookup = build_td_to_sackmann_map(sack_names)

    sack_year_set = {d.year for _, _, _, d in sack}
    missing_years = [y for y in years if y not in sack_year_set]
    td = load_tennis_data(tour, missing_years, dest_dir, name_lookup=lookup) if missing_years else []

    log.info(
        "%s: %d Sackmann matches + %d tennis-data matches (years missing from Sackmann: %s)",
        tour, len(sack), len(td), missing_years or "none",
    )
    combined = sack + td
    combined.sort(key=lambda r: r[3])
    return combined
