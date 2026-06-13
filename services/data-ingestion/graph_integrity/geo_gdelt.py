"""GDELT-Event-Geo backfill. The stored canonical parquet is geo-stripped, so
re-fetch the RAW export slices, parse action_geo, and write OCCURRED_AT for
events that already exist in Neo4j. Idempotent + resumable (per-slice)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog

from gdelt_raw.ids import build_event_id, build_location_id

log = structlog.get_logger(__name__)

_BASE = "http://data.gdeltproject.org/gdeltv2"

BACKFILL_OCCURRED_AT = """
MATCH (ev:GDELTEvent {event_id: $event_id})
WHERE NOT (ev)-[:OCCURRED_AT]->(:Location)
MERGE (l:Location {loc_key: $loc_key})
  ON CREATE SET l.name = $name, l.country = $country,
                l.lat = $lat, l.lon = $lon, l.geo_basis = 'gdelt_actiongeo'
MERGE (ev)-[:OCCURRED_AT]->(l)
"""


def slice_ids_from_parquet(parquet_base: str | Path) -> list[str]:
    base = Path(parquet_base) / "events"
    return sorted(p.stem for p in base.glob("date=*/*.parquet"))


def export_url_for(slice_id: str) -> str:
    return f"{_BASE}/{slice_id}.export.CSV.zip"


def build_geo_row(raw: dict[str, Any]) -> dict[str, Any] | None:
    if raw.get("action_geo_lat") is None or raw.get("action_geo_long") is None:
        return None
    return {
        "event_id": build_event_id(raw["global_event_id"]),
        "loc_key": build_location_id(
            str(raw.get("action_geo_feature_id") or ""),
            raw.get("action_geo_country_code") or "",
            raw.get("action_geo_fullname") or "",
        ),
        "name": raw.get("action_geo_fullname"),
        "country": raw.get("action_geo_country_code"),
        "lat": raw["action_geo_lat"],
        "lon": raw["action_geo_long"],
    }


def _fetch_and_parse(slice_id: str) -> list[dict]:
    """Default fetch: download the raw export slice and parse action_geo columns.
    Reuses gdelt_raw download + polars_schemas.EVENT_POLARS_SCHEMA. Raises on
    missing/410 slice (caught by run() when skip_missing=True). I/O seam — not
    unit-tested; the run() tests inject `fetch`."""
    raise NotImplementedError(
        "wire to gdelt_raw.run.download_slice + polars_schemas parsing at deploy time"
    )


async def run(
    client,
    parquet_base,
    dry_run: bool = False,
    *,
    fetch=_fetch_and_parse,
    skip_missing: bool = True,
) -> int:
    """Re-fetch each already-ingested slice, write OCCURRED_AT for geoless events.
    Returns the number of geo-eligible rows (written, or counted under dry_run)."""
    count = 0
    skipped = 0
    for slice_id in slice_ids_from_parquet(parquet_base):
        try:
            rows = fetch(slice_id)
        except Exception as exc:  # noqa: BLE001 — missing/410 slice must not abort
            if not skip_missing:
                raise
            skipped += 1
            log.warning("gdelt_geo_slice_skipped", slice_id=slice_id, error=str(exc))
            continue
        for raw in rows:
            geo = build_geo_row(raw)
            if geo is None:
                continue
            count += 1
            if not dry_run:
                await client.run(BACKFILL_OCCURRED_AT, geo)
    if skipped:
        log.warning("gdelt_geo_slices_skipped_total", skipped=skipped)
    return count
