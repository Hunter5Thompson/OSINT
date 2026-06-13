"""Vendored from graph_integrity.loc_key — backend has a separate build context
and cannot import data-ingestion. Kept in sync by test_vendored_loc_key_matches_canonical."""
from __future__ import annotations

import re
import unicodedata

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slug(s: str) -> str:
    norm = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return _SLUG_RE.sub("-", norm.lower()).strip("-")


def incident_key(name: str | None, lat: float, lon: float) -> str:
    if name and name.strip():
        return f"incident:{slug(name)}"
    return f"geo:{lat:.3f},{lon:.3f}"
