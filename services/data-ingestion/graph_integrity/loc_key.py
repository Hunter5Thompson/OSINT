"""Deterministic Location identity keys. Pure, no I/O."""
from __future__ import annotations

import re
import unicodedata

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slug(s: str) -> str:
    norm = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return _SLUG_RE.sub("-", norm.lower()).strip("-")


def centroid_key(iso2: str) -> str:
    return f"centroid:{iso2.lower()}"


def incident_key(name: str | None, lat: float, lon: float) -> str:
    # Coordinates are ALWAYS part of the identity, even when a name is present
    # (WP-07): two distinct incidents that share a location slug but sit at
    # different coordinates must NOT collapse onto the same :Location node.
    if name and name.strip():
        return f"incident:{slug(name)}@{lat:.3f},{lon:.3f}"
    return f"geo:{lat:.3f},{lon:.3f}"
