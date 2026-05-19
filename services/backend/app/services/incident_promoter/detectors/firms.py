"""FIRMS Geo-Cluster Detector.

Watches FIRMS signals (``payload.source == "firms"``), buckets them by
rounded lat/lon, and ignites a cluster once ``firms_min_hits`` detections
accumulate inside the configured window.
"""
from __future__ import annotations

import re

_COORD_RE = re.compile(
    r"@(?P<lat>-?\d+(?:\.\d+)?),(?P<lon>-?\d+(?:\.\d+)?),"
)


def _parse_firms_coords(url: str | None) -> tuple[float, float] | None:
    """Return ``(lat, lon)`` extracted from a FIRMS map URL, or ``None``."""
    if not url:
        return None
    match = _COORD_RE.search(url)
    if not match:
        return None
    try:
        return float(match.group("lat")), float(match.group("lon"))
    except ValueError:
        return None


def _bucket_key(lat: float, lon: float, *, deg: float) -> str:
    """Snap coords to a ``deg``-degree grid for cluster membership.

    Rounding uses ``round(x, 1)`` when ``deg == 0.1``; this matches the
    "~11 km cell" sizing described in the spec. For other ``deg`` values
    we fall back to integer-multiple rounding.
    """
    if deg == 0.1:
        lat_b = round(lat, 1)
        lon_b = round(lon, 1)
    else:
        lat_b = round(lat / deg) * deg
        lon_b = round(lon / deg) * deg
        # avoid -0.0 in keys
        lat_b = lat_b + 0.0
        lon_b = lon_b + 0.0

    # Format with proper decimal places: preserve .0 for whole numbers
    def fmt(x: float) -> str:
        s = f"{x:.1f}" if deg == 0.1 else str(x)
        return s

    return f"firms:geo:{fmt(lat_b)}:{fmt(lon_b)}"
