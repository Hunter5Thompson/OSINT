"""Shared restartable batch engine for Spatial Scope normalization jobs."""

from __future__ import annotations

import hashlib
import json
import math
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import ValidationError

from graph_integrity.spatial_normalizer import (
    CountryCodeSystem,
    RawLocationIdentity,
    SpatialNormalizationIndex,
    SpatialNormalizationResult,
    normalize_location,
    spatial_property_parameters,
)

type JobKind = Literal["backfill", "reenrichment"]

SUPPORTED_LOCATION_LANES = (
    "backend_incident",
    "gdelt_raw",
    "military_aircraft",
    "rss_pipeline",
)

_FETCH_PROJECTION = """
RETURN l.loc_key AS record_id,
       l.name AS name, l.country AS country,
       l.lat AS lat, l.lon AS lon, l.geo_basis AS geo_basis,
       l.source_country_code AS source_country_code,
       l.source_country_code_system AS source_country_code_system,
       l.country_iso3 AS country_iso3,
       l.admin1_code AS admin1_code, l.admin2_code AS admin2_code,
       l.country_scope_key AS country_scope_key,
       l.admin1_scope_key AS admin1_scope_key,
       l.admin2_scope_key AS admin2_scope_key,
       l.spatial_basis AS spatial_basis,
       l.spatial_precision AS spatial_precision,
       l.spatial_catalog_revision AS spatial_catalog_revision,
       l.spatial_derivation_revision AS spatial_derivation_revision,
       l.spatial_conflict AS spatial_conflict,
       l.spatial_conflict_scope_keys AS spatial_conflict_scope_keys,
       l.geo IS NOT NULL AS has_geo
ORDER BY l.loc_key
LIMIT $batch_size
"""

FETCH_LOCATION_BATCHES = {
    "backend_incident": """
MATCH (l:Location)
WHERE l.loc_key STARTS WITH 'incident:'
  AND ($cursor IS NULL OR l.loc_key > $cursor)
"""
    + _FETCH_PROJECTION,
    "gdelt_raw": """
MATCH (l:Location)
WHERE l.loc_key STARTS WITH 'gdelt:loc:'
  AND ($cursor IS NULL OR l.loc_key > $cursor)
"""
    + _FETCH_PROJECTION,
    "military_aircraft": """
MATCH (l:Location)
WHERE l.loc_key STARTS WITH 'aircraft-observation:'
  AND ($cursor IS NULL OR l.loc_key > $cursor)
"""
    + _FETCH_PROJECTION,
    "rss_pipeline": """
MATCH (l:Location)
WHERE (l.loc_key STARTS WITH 'centroid:'
       OR l.loc_key STARTS WITH 'spatial:country:')
  AND ($cursor IS NULL OR l.loc_key > $cursor)
"""
    + _FETCH_PROJECTION,
}

COUNT_UNSTABLE_LOCATION_RECORDS = {
    "backend_incident": """
MATCH (l:Location)
WHERE l.loc_key IS NULL AND l.geo_basis = 'incident_report'
RETURN count(l) AS count
""",
    "gdelt_raw": """
MATCH (l:Location)
WHERE l.loc_key IS NULL AND l.geo_basis = 'gdelt_actiongeo'
RETURN count(l) AS count
""",
    "military_aircraft": """
MATCH (l:Location)
WHERE l.loc_key IS NULL AND l.type = 'geopolitical_hotspot'
RETURN count(l) AS count
""",
    "rss_pipeline": """
MATCH (l:Location)
WHERE l.loc_key IS NULL
  AND l.geo_basis IN ['country_centroid', 'source_country_code']
RETURN count(l) AS count
""",
}

APPLY_SPATIAL_BATCH = """
UNWIND $rows AS row
MATCH (l:Location {loc_key: row.record_id})
FOREACH (_ IN CASE WHEN row.action = 'resolved' THEN [1] ELSE [] END |
  SET l.source_country_code = row.source_country_code,
      l.source_country_code_system = row.source_country_code_system,
      l.country_iso3 = row.country_iso3,
      l.admin1_code = row.admin1_code,
      l.admin2_code = row.admin2_code,
      l.country_scope_key = row.country_scope_key,
      l.admin1_scope_key = row.admin1_scope_key,
      l.admin2_scope_key = row.admin2_scope_key,
      l.spatial_basis = row.spatial_basis,
      l.spatial_precision = row.spatial_precision,
      l.spatial_catalog_revision = row.spatial_catalog_revision,
      l.spatial_derivation_revision = row.spatial_derivation_revision,
      l.spatial_conflict = row.spatial_conflict,
      l.spatial_conflict_scope_keys = row.spatial_conflict_scope_keys,
      l.geo = CASE
        WHEN row.latitude IS NULL OR row.longitude IS NULL THEN l.geo
        ELSE point({longitude: row.longitude, latitude: row.latitude})
      END
)
FOREACH (_ IN CASE WHEN row.action = 'conflict' THEN [1] ELSE [] END |
  SET l.spatial_catalog_revision = row.spatial_catalog_revision,
      l.spatial_conflict = true,
      l.spatial_conflict_scope_keys = row.spatial_conflict_scope_keys
)
RETURN count(l) AS updated
"""


class SpatialBatchClient(Protocol):
    async def run(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]: ...


@dataclass(frozen=True, slots=True)
class BatchJob:
    job_kind: JobKind
    lane: str
    target_derivation_revision: str
    batch_size: int = 500
    target_scope_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.lane not in FETCH_LOCATION_BATCHES:
            raise ValueError(f"unsupported spatial lane: {self.lane}")
        if not self.target_derivation_revision:
            raise ValueError("target derivation revision is required")
        if not 1 <= self.batch_size <= 10_000:
            raise ValueError("batch size must be between 1 and 10000")
        if tuple(sorted(set(self.target_scope_keys))) != self.target_scope_keys:
            raise ValueError("target scope keys must be unique and sorted")

    @property
    def checkpoint_key(self) -> str:
        return "|".join((self.job_kind, self.lane, self.target_derivation_revision))

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_kind": self.job_kind,
            "lane": self.lane,
            "target_derivation_revision": self.target_derivation_revision,
            "target_scope_keys": list(self.target_scope_keys),
            "batch_size": self.batch_size,
        }


class CheckpointStore(Protocol):
    def load(self, job: BatchJob) -> str | None: ...

    def save(self, job: BatchJob, cursor: str) -> None: ...


class MemoryCheckpointStore:
    """In-memory checkpoint seam for embedding and hermetic tests."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def load(self, job: BatchJob) -> str | None:
        return self.values.get(job.checkpoint_key)

    def save(self, job: BatchJob, cursor: str) -> None:
        self.values[job.checkpoint_key] = cursor


class JsonCheckpointStore:
    """Atomic JSON checkpoint store keyed by job kind, lane and target revision."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self, job: BatchJob) -> str | None:
        return self._read().get(job.checkpoint_key)

    def save(self, job: BatchJob, cursor: str) -> None:
        values = self._read()
        values[job.checkpoint_key] = cursor
        payload = {
            "schema_version": 1,
            "checkpoints": [
                {"job_key": key, "last_record_id": value} for key, value in sorted(values.items())
            ],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(_canonical_json(payload))
            temporary_path = Path(temporary.name)
        temporary_path.replace(self.path)

    def _read(self) -> dict[str, str]:
        if self.path.is_symlink():
            raise ValueError("checkpoint path must be a regular file")
        if not self.path.exists():
            return {}
        if not self.path.is_file():
            raise ValueError("checkpoint path must be a regular file")
        payload = json.loads(self.path.read_text())
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise ValueError("unsupported spatial checkpoint schema")
        entries = payload.get("checkpoints")
        if not isinstance(entries, list):
            raise ValueError("invalid spatial checkpoints")
        values: dict[str, str] = {}
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {
                "job_key",
                "last_record_id",
            }:
                raise ValueError("invalid spatial checkpoint entry")
            key = entry["job_key"]
            cursor = entry["last_record_id"]
            if not isinstance(key, str) or not isinstance(cursor, str):
                raise ValueError("invalid spatial checkpoint value")
            values[key] = cursor
        return values


@dataclass(slots=True)
class _Report:
    job: BatchJob
    catalog_revision: str
    dry_run: bool
    start_cursor: str | None
    end_cursor: str | None = None
    total: int = 0
    already_normalized: int = 0
    resolvable: int = 0
    unresolved: int = 0
    conflict: int = 0
    invalid_coordinate: int = 0
    target_revision_mismatch: int = 0
    writes_planned: int = 0
    writes_applied: int = 0
    stale_compatible_revision_count: int = 0
    country_addressable: int = 0
    country_scoped: int = 0
    unstable_record_id_count: int = 0
    by_source: Counter[str] = field(default_factory=Counter, init=False)
    by_code_system: Counter[str] = field(default_factory=Counter, init=False)

    def to_dict(self) -> dict[str, Any]:
        coverage = (
            self.country_scoped / self.country_addressable if self.country_addressable else 0.0
        )
        stale_rate = (
            self.stale_compatible_revision_count / self.country_addressable
            if self.country_addressable
            else 0.0
        )
        report = {
            "schema_version": 1,
            "mode": "dry-run" if self.dry_run else "apply",
            "catalog_revision": self.catalog_revision,
            "job": self.job.to_dict(),
            "start_cursor": self.start_cursor,
            "end_cursor": self.end_cursor,
            "complete": self.unstable_record_id_count == 0,
            "total": self.total,
            "already_normalized": self.already_normalized,
            "resolvable": self.resolvable,
            "unresolved": self.unresolved,
            "conflict": self.conflict,
            "invalid_coordinate": self.invalid_coordinate,
            "target_revision_mismatch": self.target_revision_mismatch,
            "writes_planned": self.writes_planned,
            "writes_applied": self.writes_applied,
            "unstable_record_id_count": self.unstable_record_id_count,
            "by_source": dict(sorted(self.by_source.items())),
            "by_code_system": dict(sorted(self.by_code_system.items())),
            "country_addressable": self.country_addressable,
            "country_scoped": self.country_scoped,
            "country_coverage_ratio": coverage,
            "stale_compatible_revision_count": (self.stale_compatible_revision_count),
            "stale_compatible_revision_rate": stale_rate,
        }
        report["report_fingerprint"] = report_fingerprint(report)
        return report


async def run_spatial_batch(
    client: SpatialBatchClient,
    spatial_index: SpatialNormalizationIndex,
    checkpoints: CheckpointStore,
    job: BatchJob,
    *,
    dry_run: bool,
) -> dict[str, Any]:
    """Run one lane/revision job; checkpoint only fully applied batches."""

    cursor = checkpoints.load(job)
    report = _Report(
        job=job,
        catalog_revision=spatial_index.catalog_revision,
        dry_run=dry_run,
        start_cursor=cursor,
        end_cursor=cursor,
    )
    report.unstable_record_id_count = _single_count(
        await client.run(COUNT_UNSTABLE_LOCATION_RECORDS[job.lane])
    )
    while True:
        rows = await client.run(
            FETCH_LOCATION_BATCHES[job.lane],
            {"cursor": cursor, "batch_size": job.batch_size},
        )
        if not rows:
            break
        _validate_batch(rows, cursor=cursor, batch_size=job.batch_size)
        updates: list[dict[str, Any]] = []
        for row in rows:
            _account_row(report, row, job.lane)
            update = _plan_update(row, job, spatial_index, report)
            if update is not None:
                updates.append(update)

        report.writes_planned += len(updates)
        if not dry_run and updates:
            result = await client.run(APPLY_SPATIAL_BATCH, {"rows": updates})
            updated = _updated_count(result)
            if updated != len(updates):
                raise RuntimeError(f"spatial batch updated {updated} of {len(updates)} records")
            report.writes_applied += updated

        cursor = rows[-1]["record_id"]
        report.end_cursor = cursor
        if not dry_run:
            checkpoints.save(job, cursor)
        if len(rows) < job.batch_size:
            break
    return report.to_dict()


def report_fingerprint(report: dict[str, Any]) -> str:
    payload = {key: value for key, value in report.items() if key != "report_fingerprint"}
    return hashlib.sha256(_canonical_json(payload).encode()).hexdigest()


def validate_dry_run_approval(
    approved_report: dict[str, Any],
    fresh_dry_run: dict[str, Any],
) -> None:
    if approved_report.get("mode") != "dry-run":
        raise ValueError("approved report is not a dry-run")
    if approved_report.get("complete") is not True:
        raise ValueError("approved dry-run is incomplete")
    fingerprint = approved_report.get("report_fingerprint")
    if not isinstance(fingerprint, str) or fingerprint != report_fingerprint(approved_report):
        raise ValueError("approved dry-run fingerprint is invalid")
    if fingerprint != report_fingerprint(fresh_dry_run):
        raise ValueError("approved dry-run drifted from the current graph")


def _account_row(report: _Report, row: dict[str, Any], lane: str) -> None:
    report.total += 1
    source = row.get("geo_basis") or lane
    report.by_source[str(source)] += 1
    report.by_code_system[_code_system_label(row, lane)] += 1


def _plan_update(
    row: dict[str, Any],
    job: BatchJob,
    spatial_index: SpatialNormalizationIndex,
    report: _Report,
) -> dict[str, Any] | None:
    try:
        raw = _raw_identity(row, job.lane)
    except (TypeError, ValueError, ValidationError):
        if _has_invalid_coordinate(row, job.lane):
            report.invalid_coordinate += 1
        else:
            report.unresolved += 1
        return None

    result = normalize_location(raw, spatial_index)
    if result.country_scope_key is not None:
        report.country_addressable += 1
        if not result.spatial_conflict:
            report.country_scoped += 1
    existing_revision = row.get("spatial_derivation_revision")
    assigned_scope = result.admin2_scope_key or result.admin1_scope_key or result.country_scope_key
    if (
        existing_revision is not None
        and result.spatial_derivation_revision is not None
        and existing_revision != result.spatial_derivation_revision
        and assigned_scope is not None
        and spatial_index.is_compatible_derivation(
            assigned_scope,
            existing_revision,
        )
    ):
        report.stale_compatible_revision_count += 1

    if result.status == "unresolved":
        report.unresolved += 1
        return None
    if result.status == "conflict":
        if _conflict_is_current(row, result):
            report.already_normalized += 1
            return None
        report.conflict += 1
        return {
            "record_id": row["record_id"],
            "action": "conflict",
            "spatial_catalog_revision": result.spatial_catalog_revision,
            "spatial_conflict_scope_keys": list(result.spatial_conflict_scope_keys),
        }
    if not _targets_job(result, job):
        report.target_revision_mismatch += 1
        return None
    if _resolved_is_current(row, result):
        report.already_normalized += 1
        return None

    report.resolvable += 1
    return {
        "record_id": row["record_id"],
        "action": "resolved",
        "latitude": result.latitude,
        "longitude": result.longitude,
        **spatial_property_parameters(result),
    }


def _raw_identity(row: dict[str, Any], lane: str) -> RawLocationIdentity:
    code = row.get("source_country_code")
    system_value = row.get("source_country_code_system")
    if code is None and lane == "gdelt_raw":
        code = row.get("country")
        system_value = system_value or CountryCodeSystem.GDELT_GEC.value
    elif code is None and lane == "rss_pipeline":
        code = _rss_country_code(str(row["record_id"]))
        system_value = system_value or CountryCodeSystem.ISO2.value

    system = CountryCodeSystem(system_value) if system_value is not None else None
    latitude = row.get("lat")
    longitude = row.get("lon")
    if lane == "rss_pipeline" and str(row["record_id"]).startswith("centroid:"):
        latitude = None
        longitude = None
    name = row.get("name")
    return RawLocationIdentity(
        country_code=code,
        country_code_system=system,
        source_country_name=name if isinstance(name, str) and name else None,
        latitude=latitude,
        longitude=longitude,
    )


def _rss_country_code(record_id: str) -> str | None:
    for prefix in ("centroid:", "spatial:country:"):
        if record_id.startswith(prefix):
            code = record_id.removeprefix(prefix).upper()
            return code if len(code) == 2 and code.isalpha() else None
    return None


def _code_system_label(row: dict[str, Any], lane: str) -> str:
    existing = row.get("source_country_code_system")
    if existing:
        return str(existing)
    if lane == "gdelt_raw":
        return CountryCodeSystem.GDELT_GEC.value
    if lane == "rss_pipeline":
        return CountryCodeSystem.ISO2.value
    return "none"


def _has_invalid_coordinate(row: dict[str, Any], lane: str) -> bool:
    if lane == "rss_pipeline" and str(row.get("record_id", "")).startswith("centroid:"):
        return False
    latitude = row.get("lat")
    longitude = row.get("lon")
    if (latitude is None) != (longitude is None):
        return True
    if latitude is None:
        return False
    return not (
        isinstance(latitude, int | float)
        and not isinstance(latitude, bool)
        and math.isfinite(latitude)
        and -90 <= latitude <= 90
        and isinstance(longitude, int | float)
        and not isinstance(longitude, bool)
        and math.isfinite(longitude)
        and -180 <= longitude <= 180
    )


def _targets_job(result: SpatialNormalizationResult, job: BatchJob) -> bool:
    if result.spatial_derivation_revision != job.target_derivation_revision:
        return False
    if not job.target_scope_keys:
        return True
    assigned = {
        value
        for value in (
            result.country_scope_key,
            result.admin1_scope_key,
            result.admin2_scope_key,
        )
        if value is not None
    }
    return not assigned.isdisjoint(job.target_scope_keys)


def _resolved_is_current(
    row: dict[str, Any],
    result: SpatialNormalizationResult,
) -> bool:
    projection = spatial_property_parameters(result)
    for key, value in projection.items():
        existing = row.get(key)
        if key == "spatial_conflict_scope_keys" and existing is None:
            existing = []
        if existing != value:
            return False
    return result.latitude is None or bool(row.get("has_geo"))


def _conflict_is_current(
    row: dict[str, Any],
    result: SpatialNormalizationResult,
) -> bool:
    return (
        row.get("spatial_catalog_revision") == result.spatial_catalog_revision
        and row.get("spatial_conflict") is True
        and (row.get("spatial_conflict_scope_keys") or [])
        == list(result.spatial_conflict_scope_keys)
    )


def _validate_batch(
    rows: list[dict[str, Any]],
    *,
    cursor: str | None,
    batch_size: int,
) -> None:
    if len(rows) > batch_size:
        raise RuntimeError("spatial batch exceeded requested size")
    record_ids = [row.get("record_id") for row in rows]
    if any(not isinstance(record_id, str) or not record_id for record_id in record_ids):
        raise RuntimeError("spatial batch contains an unstable record id")
    if record_ids != sorted(set(record_ids)):
        raise RuntimeError("spatial batch is not strictly ordered")
    if cursor is not None and record_ids[0] <= cursor:
        raise RuntimeError("spatial batch did not advance its stable cursor")


def _updated_count(rows: list[dict[str, Any]]) -> int:
    if len(rows) != 1 or not isinstance(rows[0].get("updated"), int):
        raise RuntimeError("spatial batch returned invalid update accounting")
    return int(rows[0]["updated"])


def _single_count(rows: list[dict[str, Any]]) -> int:
    if len(rows) != 1 or not isinstance(rows[0].get("count"), int):
        raise RuntimeError("spatial preflight returned invalid accounting")
    count = int(rows[0]["count"])
    if count < 0:
        raise RuntimeError("spatial preflight returned a negative count")
    return count


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
