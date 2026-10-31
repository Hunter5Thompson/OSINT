"""Vendored from graph_integrity.loc_key — backend has a separate build context
and cannot import data-ingestion. Kept in sync by test_vendored_loc_key_matches_canonical."""

from __future__ import annotations

import re
import unicodedata

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slug(s: str) -> str:
    norm = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return _SLUG_RE.sub("-", norm.lower()).strip("-")


def _prefix(name: str | None) -> str:
    # Coordinates are ALWAYS part of the identity, even when a name is present
    # (WP-07): two distinct incidents that share a location slug but sit at
    # different coordinates must NOT collapse onto the same :Location node.
    return f"incident:{slug(name)}@" if name and name.strip() else "geo:"


def legacy_incident_key(name: str | None, lat: float, lon: float) -> str:
    """Original algorithm for reviewed historical repair plans only."""
    return f"{_prefix(name)}{lat:.3f},{lon:.3f}"


def incident_key(name: str | None, lat: float, lon: float) -> str:
    rounded_lat, rounded_lon = round(lat, 3), round(lon, 3)
    if rounded_lat == 0:
        rounded_lat = 0.0
    if rounded_lon == 0:
        rounded_lon = 0.0
    return legacy_incident_key(name, rounded_lat, rounded_lon)


def incident_key_candidates(name: str | None, lat: float, lon: float) -> tuple[str, ...]:
    """Canonical first; bounded signed-zero aliases for compatible writes."""
    rounded_lat, rounded_lon = round(lat, 3), round(lon, 3)
    latitudes = ("0.000", "-0.000") if rounded_lat == 0 else (f"{lat:.3f}",)
    longitudes = ("0.000", "-0.000") if rounded_lon == 0 else (f"{lon:.3f}",)
    return tuple(
        f"{_prefix(name)}{latitude},{longitude}"
        for latitude in latitudes
        for longitude in longitudes
    )
