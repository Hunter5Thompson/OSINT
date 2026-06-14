"""GDELT-Event-Geo backfill. The stored canonical parquet is geo-stripped, so
re-fetch the RAW export slices, parse action_geo, and write OCCURRED_AT for
events that already exist in Neo4j. Idempotent + resumable (per-slice)."""
from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path
from typing import Any

import httpx
import structlog

from gdelt_raw.ids import build_event_id, build_location_id
from gdelt_raw.parser import parse_events

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


def _download_export(slice_id: str, dest_dir: Path) -> Path:
    """Download + unzip the raw GDELT export slice; return the extracted CSV path.

    Raises httpx.HTTPStatusError on 404/410 (missing slice) — run() skips it."""
    url = export_url_for(slice_id)
    zpath = dest_dir / f"{slice_id}.export.CSV.zip"
    resp = httpx.get(url, timeout=60.0, follow_redirects=True)
    resp.raise_for_status()
    zpath.write_bytes(resp.content)
    with zipfile.ZipFile(zpath) as z:
        z.extractall(dest_dir)
        return dest_dir / z.namelist()[0]


def _fetch_and_parse(slice_id: str) -> list[dict]:
    """Download the raw export slice and parse it into raw row dicts (with
    action_geo_* columns) via the existing gdelt_raw parser.

    Raises on missing/410 slice (httpx.HTTPStatusError) — caught by run()
    when skip_missing=True. I/O seam: the parse logic is covered by gdelt_raw
    parser tests; the run() loop is covered by injected-fetch tests."""
    with tempfile.TemporaryDirectory() as tmp:
        tmpd = Path(tmp)
        csv_path = _download_export(slice_id, tmpd)
        res = parse_events(csv_path, quarantine_dir=tmpd / "quarantine")
        return res.df.to_dicts()


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
