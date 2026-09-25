"""Shared write-side provenance helper. Facts only — no credibility, no guessing.

Provides the source-identification subset of contracts/qdrant-provenance-v1.json:
`source_type` + `provider` (+ optional `published_at`). The third required field,
`ingested_at`, is set by the caller at point-write time via `ingestion_timestamps()`.
Credibility is read-side policy and must NOT be written here.
"""
from __future__ import annotations

from datetime import UTC, datetime

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
) -> dict[str, str]:
    """Validated canonical provenance facts. Raises ValueError on bad input."""
    if source_type not in WRITE_SOURCE_TYPES:
        raise ValueError(f"invalid write source_type: {source_type!r}")
    if not provider:
        raise ValueError("provider must be a non-empty canonical id")
    fields = {"source_type": source_type, "provider": provider}
    if published_at:
        fields["published_at"] = published_at
    return fields


def dataset_provenance(source: str, published_at: str | None = None) -> dict[str, str]:
    """Canonical provenance for a known dataset source key. Raises KeyError if unknown."""
    return provenance_fields(
        source_type="dataset",
        provider=DATASET_PROVIDERS[source],
        published_at=published_at,
    )


def ingestion_timestamps() -> dict[str, str | float]:
    """Point-write stamps from ONE instant: ISO `ingested_at` + numeric `ingested_epoch`.

    `ingested_epoch` is the range-indexed field the backend feed-freshness watchdog
    orders by; every Qdrant writer must emit both.
    """
    now = datetime.now(UTC)
    return {"ingested_at": now.isoformat(), "ingested_epoch": now.timestamp()}
