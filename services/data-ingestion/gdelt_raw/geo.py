"""Location payload builder — produces Neo4j-point-ready dict."""

from __future__ import annotations

from typing import Any

from gdelt_raw.ids import build_location_id


def build_location_payload(
    feature_id: str,
    name: str,
    country_code: str,
    lat: float | None,
    lon: float | None,
) -> dict[str, Any] | None:
    """Return dict ready for Cypher MERGE, or None if coords missing/zero."""
    if lat is None or lon is None:
        return None
    if lat == 0.0 and lon == 0.0:
        return None

    fid = feature_id or build_location_id(
        feature_id="", country_code=country_code, name=name,
    )
    return {
        "feature_id": fid,
        "name": name,
        "country_code": country_code,
        "lat": lat,
        "lon": lon,
        "geo": {"latitude": lat, "longitude": lon, "crs": "wgs-84"},
    }
