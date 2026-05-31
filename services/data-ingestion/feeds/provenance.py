"""Shared write-side provenance helper. Facts only — no credibility, no guessing.

Mirrors contracts/qdrant-provenance-v1.json. Credibility is read-side policy and
must NOT be written here.
"""
from __future__ import annotations

WRITE_SOURCE_TYPES = {"rss", "telegram", "gdelt", "notebooklm", "dataset"}

# Canonical provider id per single-provider dataset source.
DATASET_PROVIDERS: dict[str, str] = {
    "firms": "firms.modaps.eosdis.nasa.gov",
    "usgs": "usgs.gov",
    "ucdp": "ucdp.uu.se",
    "ofac": "ofac.treasury.gov",
    "hapi": "hapi.humdata.org",
    "noaa_nhc": "nhc.noaa.gov",
    "portwatch": "portwatch.imf.org",
    "eonet": "eonet.gsfc.nasa.gov",
    "gdacs": "gdacs.org",
}


def provenance_fields(
    *, source_type: str, provider: str, published_at: str | None = None,
) -> dict:
    """Validated canonical provenance facts. Raises ValueError on bad input."""
    if source_type not in WRITE_SOURCE_TYPES:
        raise ValueError(f"invalid write source_type: {source_type!r}")
    if not provider:
        raise ValueError("provider must be a non-empty canonical id")
    fields = {"source_type": source_type, "provider": provider}
    if published_at:
        fields["published_at"] = published_at
    return fields


def dataset_provenance(source: str, published_at: str | None = None) -> dict:
    """Canonical provenance for a known dataset source key. Raises KeyError if unknown."""
    return provenance_fields(
        source_type="dataset",
        provider=DATASET_PROVIDERS[source],
        published_at=published_at,
    )
