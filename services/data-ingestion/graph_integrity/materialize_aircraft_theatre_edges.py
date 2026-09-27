"""Materialize historical aircraft SPOTTED_AT edges as observation Locations.

Before observation-keyed aircraft Locations existed, the collector attached every
sighting to one of nine coordinate-free theatre aggregates (``ukraine``, ``iran``,
...), named after overlapping hotspot boxes. The sighting's position survived only
on the edge. This job moves each such edge onto its own ``aircraft-observation:``
Location, built exactly like the live producer builds one, so the graph carries
catalog-derived country labels instead of box names.

Properties:
  * The complete original edge map is the drift guard and is copied verbatim
    (including the millisecond ``timestamp``) onto the new relationship.
  * Each edge is moved in one statement: create Location + edge, delete the old
    edge. An edge is never on both targets, so readers never double-count.
  * Evidence that cannot be materialized stays on its theatre aggregate and is
    reported. Theatre nodes are never deleted.
  * Moved edges leave the fetch set, so re-runs are idempotent without checkpoints.
  * ``revert`` restores the theatre edges from the recorded provenance.

Operational order: --dry-run → review report → --apply --approved-report.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from typing import Any

import structlog

from feeds.military_aircraft_collector import observation_place_name
from graph_integrity.spatial_batch import SpatialBatchClient, report_fingerprint
from graph_integrity.spatial_normalizer import (
    RawLocationIdentity,
    SpatialNormalizationIndex,
    normalize_location,
    spatial_property_parameters,
)

log = structlog.get_logger(__name__)

MATERIALIZATION_REVISION = "aircraft-theatre-edge-v1"

FETCH_THEATRE_EDGES = """
MATCH (a:MilitaryAircraft)-[r:SPOTTED_AT]->(t:Location)
WHERE t.loc_key IS NULL AND t.type = 'geopolitical_hotspot'
  AND t.lat IS NULL AND t.lon IS NULL AND t.geo IS NULL
  AND ($cursor IS NULL OR r.dedup_key > $cursor)
RETURN a.icao24 AS icao24, t.name AS theatre, r.dedup_key AS dedup_key,
       properties(r) AS edge
ORDER BY r.dedup_key
LIMIT $batch_size
"""

COUNT_EXISTING_OBSERVATION_KEYS = """
UNWIND $loc_keys AS loc_key
MATCH (l:Location {loc_key: loc_key})
RETURN count(l) AS count
"""

APPLY_MATERIALIZATION = """
UNWIND $rows AS row
MATCH (a:MilitaryAircraft {icao24: row.icao24})
      -[old:SPOTTED_AT {dedup_key: row.dedup_key}]->(t:Location)
WHERE t.loc_key IS NULL AND t.type = 'geopolitical_hotspot' AND t.name = row.theatre
  AND t.lat IS NULL AND t.lon IS NULL AND t.geo IS NULL
  AND properties(old) = row.edge
CREATE (l:Location {loc_key: row.loc_key})
SET l.name = row.name, l.type = 'aircraft_observation',
    l.lat = row.latitude, l.lon = row.longitude,
    l.geo = point({longitude: row.longitude, latitude: row.latitude}),
    l.source_country_code = row.source_country_code,
    l.source_country_code_system = row.source_country_code_system,
    l.country_iso3 = row.country_iso3,
    l.admin1_code = row.admin1_code, l.admin2_code = row.admin2_code,
    l.country_scope_key = row.country_scope_key,
    l.admin1_scope_key = row.admin1_scope_key,
    l.admin2_scope_key = row.admin2_scope_key,
    l.spatial_basis = row.spatial_basis,
    l.spatial_precision = row.spatial_precision,
    l.spatial_catalog_revision = row.spatial_catalog_revision,
    l.spatial_derivation_revision = row.spatial_derivation_revision,
    l.spatial_conflict = row.spatial_conflict,
    l.spatial_conflict_scope_keys = row.spatial_conflict_scope_keys,
    l.spatial_label_backup_taken = true,
    l.spatial_previous_name = row.theatre,
    l.materialized_from_theatre = row.theatre,
    l.materialization_revision = row.materialization_revision
CREATE (a)-[n:SPOTTED_AT]->(l)
SET n = row.edge,
    n.materialized_from_theatre = row.theatre,
    n.materialization_revision = row.materialization_revision
DELETE old
RETURN count(n) AS moved
"""

COUNT_MATERIALIZED = """
MATCH (:MilitaryAircraft)-[n:SPOTTED_AT]->(l:Location)
WHERE n.materialization_revision = $materialization_revision
  AND l.materialization_revision = $materialization_revision
RETURN count(n) AS count
"""

REVERT_MATERIALIZATION = """
MATCH (a:MilitaryAircraft)-[n:SPOTTED_AT]->(l:Location)
WHERE n.materialization_revision = $materialization_revision
  AND l.materialization_revision = $materialization_revision
WITH a, n, l LIMIT $batch_size
OPTIONAL MATCH (t:Location {name: n.materialized_from_theatre})
WHERE t.loc_key IS NULL AND t.type = 'geopolitical_hotspot'
  AND t.lat IS NULL AND t.lon IS NULL AND t.geo IS NULL
WITH a, n, l, collect(t) AS theatres
WHERE size(theatres) = 1
WITH a, n, l, theatres[0] AS t
CREATE (a)-[old:SPOTTED_AT]->(t)
SET old = properties(n)
REMOVE old.materialized_from_theatre, old.materialization_revision
DELETE n
DELETE l
RETURN count(old) AS reverted
"""


def plan_edge(
    row: dict[str, Any],
    spatial_index: SpatialNormalizationIndex,
) -> tuple[dict[str, Any] | None, str | None]:
    """Pure: the APPLY row for one historical edge, or the reason it stays put."""

    edge = row.get("edge")
    dedup_key = row.get("dedup_key")
    icao24 = row.get("icao24")
    theatre = row.get("theatre")
    if (
        not isinstance(edge, dict)
        or not _non_empty_str(dedup_key)
        or not _non_empty_str(icao24)
        or not _non_empty_str(theatre)
        or edge.get("dedup_key") != dedup_key
    ):
        return None, "invalid_identity"

    latitude = edge.get("latitude")
    longitude = edge.get("longitude")
    if latitude is None or longitude is None:
        return None, "missing_coordinate"
    if not _valid_coordinate(latitude, 90.0) or not _valid_coordinate(longitude, 180.0):
        return None, "invalid_coordinate"
    if latitude == 0.0 and longitude == 0.0:
        return None, "null_island"
    timestamp = edge.get("timestamp")
    if isinstance(timestamp, bool) or not isinstance(timestamp, int):
        return None, "invalid_timestamp"

    normalized = normalize_location(
        RawLocationIdentity(latitude=float(latitude), longitude=float(longitude)),
        spatial_index,
    )
    return {
        "icao24": icao24,
        "theatre": theatre,
        "dedup_key": dedup_key,
        "edge": edge,
        "loc_key": f"aircraft-observation:{dedup_key}",
        "name": observation_place_name(normalized.country_iso3),
        "latitude": latitude,
        "longitude": longitude,
        "materialization_revision": MATERIALIZATION_REVISION,
        **spatial_property_parameters(normalized),
    }, None


async def run(
    client: SpatialBatchClient,
    spatial_index: SpatialNormalizationIndex,
    *,
    batch_size: int = 500,
    dry_run: bool,
) -> dict[str, Any]:
    """Scan every theatre edge; on apply, move each planned edge batch by batch."""

    if not 1 <= batch_size <= 10_000:
        raise ValueError("batch size must be between 1 and 10000")
    total = writes_planned = writes_applied = existing_keys = 0
    by_theatre: Counter[str] = Counter()
    by_name: Counter[str] = Counter()
    skipped: Counter[str] = Counter()
    inputs = hashlib.sha256()
    cursor: str | None = None
    while True:
        rows = await client.run(FETCH_THEATRE_EDGES, {"cursor": cursor, "batch_size": batch_size})
        if not rows:
            break
        _validate_page(rows, cursor=cursor, batch_size=batch_size)
        writes: list[dict[str, Any]] = []
        for row in rows:
            total += 1
            by_theatre[str(row.get("theatre"))] += 1
            write, skip = plan_edge(row, spatial_index)
            inputs.update(_canonical({"input": row, "write": write, "skip": skip}).encode())
            inputs.update(b"\n")
            if write is None:
                skipped[str(skip)] += 1
                continue
            by_name[write["name"]] += 1
            writes.append(write)

        writes_planned += len(writes)
        if writes:
            collisions = _single_count(
                await client.run(
                    COUNT_EXISTING_OBSERVATION_KEYS,
                    {"loc_keys": [w["loc_key"] for w in writes]},
                )
            )
            existing_keys += collisions
            if not dry_run:
                if collisions:
                    raise RuntimeError(
                        f"{collisions} existing observation Locations collide with planned keys"
                    )
                moved = _moved_count(await client.run(APPLY_MATERIALIZATION, {"rows": writes}))
                if moved != len(writes):
                    raise RuntimeError(f"theatre batch moved {moved} of {len(writes)} edges")
                writes_applied += moved
                log.info("aircraft_theatre_batch_moved", moved=moved, cursor=rows[-1]["dedup_key"])

        cursor = rows[-1]["dedup_key"]
        if len(rows) < batch_size:
            break

    report: dict[str, Any] = {
        "schema_version": 1,
        "mode": "dry-run" if dry_run else "apply",
        "catalog_revision": spatial_index.catalog_revision,
        "materialization_revision": MATERIALIZATION_REVISION,
        "batch_size": batch_size,
        "complete": existing_keys == 0,
        "total": total,
        "writes_planned": writes_planned,
        "writes_applied": writes_applied,
        "existing_observation_keys": existing_keys,
        "by_theatre": dict(sorted(by_theatre.items())),
        "by_name": dict(sorted(by_name.items())),
        "skipped": dict(sorted(skipped.items())),
        "input_fingerprint": inputs.hexdigest(),
    }
    report["report_fingerprint"] = report_fingerprint(report)
    return report


async def revert(client: SpatialBatchClient, *, batch_size: int = 500, dry_run: bool) -> int:
    """Move materialized edges back onto their theatre aggregate; returns the count."""

    params = {"materialization_revision": MATERIALIZATION_REVISION}
    if dry_run:
        return _single_count(await client.run(COUNT_MATERIALIZED, params))
    reverted = 0
    while True:
        rows = await client.run(REVERT_MATERIALIZATION, {**params, "batch_size": batch_size})
        if len(rows) != 1 or not isinstance(rows[0].get("reverted"), int):
            raise RuntimeError("theatre revert returned invalid accounting")
        count = int(rows[0]["reverted"])
        reverted += count
        if count == 0:
            break
    remaining = _single_count(await client.run(COUNT_MATERIALIZED, params))
    if remaining:
        raise RuntimeError(f"{remaining} materialized edges could not be reverted")
    return reverted


def _validate_page(rows: list[dict[str, Any]], *, cursor: str | None, batch_size: int) -> None:
    if len(rows) > batch_size:
        raise RuntimeError("theatre page exceeded requested size")
    keys = [row.get("dedup_key") for row in rows]
    if any(not _non_empty_str(key) for key in keys):
        raise RuntimeError("theatre page contains an edge without dedup_key")
    if keys != sorted(set(keys)):
        raise RuntimeError("theatre page is not strictly ordered")
    if cursor is not None and keys[0] <= cursor:
        raise RuntimeError("theatre page did not advance its cursor")


def _valid_coordinate(value: Any, bound: float) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
        and -bound <= value <= bound
    )


def _non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _moved_count(rows: list[dict[str, Any]]) -> int:
    if len(rows) != 1 or not isinstance(rows[0].get("moved"), int):
        raise RuntimeError("theatre batch returned invalid move accounting")
    return int(rows[0]["moved"])


def _single_count(rows: list[dict[str, Any]]) -> int:
    if len(rows) != 1 or not isinstance(rows[0].get("count"), int):
        raise RuntimeError("theatre preflight returned invalid accounting")
    return int(rows[0]["count"])


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
