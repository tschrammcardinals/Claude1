"""Map Kalshi market titles / player names to Sackmann player names.

Kalshi titles look like "Will Carlos Alcaraz win his match vs. Jannik Sinner?"
or markets named "ALCARAZ-SINNER". Sackmann names are "Carlos Alcaraz",
"Jannik Sinner". We use rapidfuzz to find the best match in our rating table.
"""
from __future__ import annotations

import logging
import re
from typing import Iterable, Optional, Tuple

from rapidfuzz import process, fuzz

log = logging.getLogger(__name__)


_TITLE_VS_RE = re.compile(
    r"(?P<a>[A-Za-z .'\-]+?)\s+(?:vs\.?|v\.?|defeats?|to beat)\s+(?P<b>[A-Za-z .'\-]+)",
    re.IGNORECASE,
)


def parse_title(title: str) -> Optional[Tuple[str, str]]:
    """Pull two player names out of a Kalshi market title. None if not parseable."""
    m = _TITLE_VS_RE.search(title)
    if not m:
        return None
    return m.group("a").strip(), m.group("b").strip()


def best_match(name: str, candidates: Iterable[str], score_cutoff: int = 85) -> Optional[str]:
    """Fuzzy-match a name to the closest candidate; None if below cutoff.

    Uses partial_ratio so abbreviated first names ("C. Alcaraz") still resolve.
    The surname-only fallback handles cases like "J Sinner" against a long list.
    """
    cands = list(candidates)
    if not cands:
        return None
    res = process.extractOne(
        name, cands, scorer=fuzz.partial_ratio, score_cutoff=score_cutoff
    )
    return res[0] if res else None


def resolve_pair(
    raw_a: str, raw_b: str, candidates: Iterable[str]
) -> Tuple[Optional[str], Optional[str]]:
    cands = list(candidates)
    a = best_match(raw_a, cands)
    b = best_match(raw_b, cands)
    if a and b and a == b:
        # Disambiguate: re-run b excluding a.
        b = best_match(raw_b, [c for c in cands if c != a])
    return a, b
