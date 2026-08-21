"""Restartable, per-point atomic Qdrant spatial re-enrichment.

The batch engine is deliberately independent of source-specific derivation.  A
trusted projector supplies one complete spatial projection for each point; this
module owns pagination, replacement, checkpointing and coverage accounting.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Final, Protocol

from qdrant_client import AsyncQdrantClient, models

from spatial import (
    SPATIAL_DERIVATION_VERSION,
    SpatialCoverageSnapshotV1,
    SpatialLaneCoverageV1,
    derive_spatial_projection_revision,
    encode_scope_revision_token,
)

_LANE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_PROJECTION_REVISION = re.compile(
    r"^spatial-projection-v[0-9]+-[a-f0-9]{12,64}$"
)
_MAX_PROMOTION_STALE_RATE: Final = 0.01
_RAW_SPATIAL_FIELDS: Final = frozenset(
    {
        "geo",
        "source_country_code",
        "source_country_code_system",
        "country_iso3",
        "admin1_code",
        "admin2_code",
    }
)
_REQUIRED_PROJECTION_FIELDS: Final = frozenset(
    {
        "spatial_about_scope_revision_tokens",
        "spatial_occurrence_scope_revision_tokens",
        "spatial_basis",
        "spatial_catalog_revision",
        "spatial_projection_revision",
        "spatial_derivation_version",
        "spatial_conflict",
        "spatial_conflict_scope_keys",
        "spatial_derivation_status",
        "spatial_derivations",
    }
)
_TOKEN_FIELDS: Final = (
    "spatial_about_scope_revision_tokens",
    "spatial_occurrence_scope_revision_tokens",
)

type PointId = str | int
type Cursor = str | int | None


class _ReenrichmentMode(StrEnum):
    """Private execution mode; the public apply interface is approval-gated."""

    DRY_RUN = "dry-run"
    APPLY = "apply"


@dataclass(frozen=True, slots=True)
class ReenrichmentJob:
    """One corpus lane projected to one semantic revision."""

    lane: str
    target_projection_revision: str
    batch_size: int = 500

    def __post_init__(self) -> None:
        if not isinstance(self.lane, str) or _LANE.fullmatch(self.lane) is None:
            raise ValueError("invalid Qdrant re-enrichment lane")
        if (
            not isinstance(self.target_projection_revision, str)
            or _PROJECTION_REVISION.fullmatch(self.target_projection_revision) is None
        ):
            raise ValueError("invalid target projection revision")
        if not 1 <= self.batch_size <= 10_000:
            raise ValueError("batch size must be between 1 and 10000")

    @property
    def checkpoint_key(self) -> str:
        return f"{self.lane}|{self.target_projection_revision}"

    def to_dict(self) -> dict[str, object]:
        return {
            "lane": self.lane,
            "target_projection_revision": self.target_projection_revision,
            "batch_size": self.batch_size,
        }


@dataclass(frozen=True, slots=True)
class Checkpoint:
    """The opaque cursor following the last fully confirmed page."""

    cursor: Cursor = None
    complete: bool = False
    approved_report_fingerprint: str | None = None

    def __post_init__(self) -> None:
        fingerprint = self.approved_report_fingerprint
        if fingerprint is not None and re.fullmatch(r"[a-f0-9]{64}", fingerprint) is None:
            raise ValueError("invalid approved report fingerprint")
        if (self.cursor is not None or self.complete) and fingerprint is None:
            raise ValueError("durable checkpoint requires an approved report fingerprint")


@dataclass(frozen=True, slots=True)
class ReenrichmentPoint:
    """All material needed for one full Qdrant point replacement."""

    point_id: PointId
    vector: object
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ReenrichmentPage:
    """One stable Qdrant scroll page and its opaque continuation cursor."""

    points: tuple[ReenrichmentPoint, ...]
    next_cursor: Cursor


class SpatialProjector(Protocol):
    """Source-owned deterministic derivation seam."""

    def project(
        self,
        point: ReenrichmentPoint,
        job: ReenrichmentJob,
    ) -> Mapping[str, object]: ...


class ReenrichmentStore(Protocol):
    """Read/full-upsert seam; implementations must not split payload updates."""

    async def fetch_page(
        self,
        lane: str,
        cursor: Cursor,
        limit: int,
    ) -> ReenrichmentPage: ...

    async def replace_points(
        self,
        lane: str,
        replacements: Sequence[ReenrichmentPoint],
    ) -> int: ...


class CheckpointStore(Protocol):
    def load(self, job: ReenrichmentJob) -> Checkpoint: ...

    def save(self, job: ReenrichmentJob, checkpoint: Checkpoint) -> None: ...


class MemoryCheckpointStore:
    """Hermetic checkpoint store for tests and embedded callers."""

    def __init__(self) -> None:
        self.values: dict[str, Checkpoint] = {}

    def load(self, job: ReenrichmentJob) -> Checkpoint:
        return self.values.get(job.checkpoint_key, Checkpoint())

    def save(self, job: ReenrichmentJob, checkpoint: Checkpoint) -> None:
        self.values[job.checkpoint_key] = checkpoint


class JsonCheckpointStore:
    """Atomic on-disk checkpoint store with a service-independent V1 format."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self, job: ReenrichmentJob) -> Checkpoint:
        return self._read().get(job.checkpoint_key, Checkpoint())

    def save(self, job: ReenrichmentJob, checkpoint: Checkpoint) -> None:
        values = self._read()
        values[job.checkpoint_key] = checkpoint
        payload = {
            "schema_version": 1,
            "checkpoints": [
                {
                    "job_key": key,
                    "cursor": value.cursor,
                    "complete": value.complete,
                    "approved_report_fingerprint": (
                        value.approved_report_fingerprint
                    ),
                }
                for key, value in sorted(values.items())
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

    def _read(self) -> dict[str, Checkpoint]:
        if self.path.is_symlink():
            raise ValueError("checkpoint path must be a regular file")
        if not self.path.exists():
            return {}
        if not self.path.is_file():
            raise ValueError("checkpoint path must be a regular file")
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise ValueError("unsupported Qdrant spatial checkpoint schema")
        entries = payload.get("checkpoints")
        if not isinstance(entries, list):
            raise ValueError("invalid Qdrant spatial checkpoints")

        values: dict[str, Checkpoint] = {}
        required_fields = frozenset({"job_key", "cursor", "complete"})
        current_fields = required_fields | {"approved_report_fingerprint"}
        for entry in entries:
            if not isinstance(entry, dict) or frozenset(entry) not in {
                required_fields,
                current_fields,
            }:
                raise ValueError("invalid Qdrant spatial checkpoint entry")
            key = entry["job_key"]
            cursor = entry["cursor"]
            complete = entry["complete"]
            approved_fingerprint = entry.get("approved_report_fingerprint")
            if (
                not isinstance(key, str)
                or not _valid_cursor(cursor)
                or not isinstance(complete, bool)
                or not isinstance(approved_fingerprint, str | None)
                or key in values
            ):
                raise ValueError("invalid Qdrant spatial checkpoint value")
            if (cursor is not None or complete) and approved_fingerprint is None:
                raise ValueError(
                    "legacy durable checkpoint lacks an approval fingerprint"
                )
            values[key] = Checkpoint(
                cursor=cursor,
                complete=complete,
                approved_report_fingerprint=approved_fingerprint,
            )
        return values


class QdrantReenrichmentStore:
    """Qdrant adapter that scrolls with lane policy and full-upserts each point."""

    def __init__(
        self,
        client: AsyncQdrantClient,
        collection_name: str,
        lane_filters: Mapping[str, models.Filter],
    ) -> None:
        if not collection_name:
            raise ValueError("Qdrant collection name is required")
        if not lane_filters or not all(
            isinstance(lane, str) and _LANE.fullmatch(lane) is not None
            and isinstance(lane_filter, models.Filter)
            for lane, lane_filter in lane_filters.items()
        ):
            raise ValueError("Qdrant lane filters must be explicit and valid")
        self._client = client
        self._collection_name = collection_name
        self._lane_filters = dict(lane_filters)

    async def fetch_page(
        self,
        lane: str,
        cursor: Cursor,
        limit: int,
    ) -> ReenrichmentPage:
        lane_filter = self._lane_filter(lane)
        records, next_cursor = await self._client.scroll(
            collection_name=self._collection_name,
            scroll_filter=lane_filter,
            limit=limit,
            offset=cursor,
            with_payload=True,
            with_vectors=True,
        )
        points: list[ReenrichmentPoint] = []
        for record in records:
            if record.payload is None or record.vector is None:
                raise RuntimeError("Qdrant re-enrichment scroll omitted payload or vector")
            points.append(
                ReenrichmentPoint(
                    point_id=record.id,
                    vector=record.vector,
                    payload=dict(record.payload),
                )
            )
        if not _valid_cursor(next_cursor):
            raise RuntimeError("Qdrant returned an unsupported scroll cursor")
        return ReenrichmentPage(points=tuple(points), next_cursor=next_cursor)

    async def replace_points(
        self,
        lane: str,
        replacements: Sequence[ReenrichmentPoint],
    ) -> int:
        self._lane_filter(lane)
        points = [
            models.PointStruct(
                id=point.point_id,
                vector=point.vector,
                payload=point.payload,
            )
            for point in replacements
        ]
        if points:
            await self._client.upsert(
                collection_name=self._collection_name,
                points=points,
                wait=True,
            )
        return len(points)

    def _lane_filter(self, lane: str) -> models.Filter:
        try:
            return self._lane_filters[lane]
        except KeyError as error:
            raise ValueError(f"unsupported Qdrant re-enrichment lane: {lane}") from error


@dataclass(slots=True)
class _Coverage:
    total_points: int = 0
    filterable_points: int = 0
    conflict_points: int = 0
    stale_points: int = 0
    unsupported_points: int = 0
    unprojected_points: int = 0
    audit_only_points: int = 0
    inconsistent_points: int = 0

    def observe(self, payload: Mapping[str, object], target_revision: str) -> None:
        self.total_points += 1
        status = _coverage_status(payload, target_revision)
        field = f"{status}_points"
        setattr(self, field, getattr(self, field) + 1)

    def snapshot(self, lane: str) -> SpatialLaneCoverageV1:
        return SpatialLaneCoverageV1(
            lane=lane,
            total_points=self.total_points,
            filterable_points=self.filterable_points,
            conflict_points=self.conflict_points,
            stale_points=self.stale_points,
            unsupported_points=self.unsupported_points,
            unprojected_points=self.unprojected_points,
            audit_only_points=self.audit_only_points,
            inconsistent_points=self.inconsistent_points,
        )


@dataclass(slots=True)
class _Report:
    job: ReenrichmentJob
    mode: _ReenrichmentMode
    start_cursor: Cursor
    end_cursor: Cursor
    complete: bool = False
    total_points: int = 0
    already_current: int = 0
    writes_planned: int = 0
    writes_applied: int = 0
    batches_completed: int = 0
    coverage_before: _Coverage = field(default_factory=_Coverage)
    coverage_projected: _Coverage = field(default_factory=_Coverage)

    def to_dict(self) -> dict[str, Any]:
        before = _coverage_snapshot(self.job, self.coverage_before)
        projected = _coverage_snapshot(self.job, self.coverage_projected)
        report: dict[str, Any] = {
            "schema_version": 1,
            "mode": self.mode.value,
            "job": self.job.to_dict(),
            "start_cursor": self.start_cursor,
            "end_cursor": self.end_cursor,
            "complete": self.complete,
            "total_points": self.total_points,
            "already_current": self.already_current,
            "writes_planned": self.writes_planned,
            "writes_applied": self.writes_applied,
            "batches_completed": self.batches_completed,
            "stale_points": self.coverage_before.stale_points,
            "stale_rate": _promotion_stale_rate(self.coverage_before),
            "unprojected_rate": _ratio(
                self.coverage_before.unprojected_points,
                self.coverage_before.total_points,
            ),
            "filterable_rate": _ratio(
                self.coverage_before.filterable_points,
                self.coverage_before.total_points,
            ),
            "projected_filterable_rate": _ratio(
                self.coverage_projected.filterable_points,
                self.coverage_projected.total_points,
            ),
            "stale_gate_passed": (
                self.coverage_before.total_points > 0
                and _promotion_stale_rate(self.coverage_before)
                <= _MAX_PROMOTION_STALE_RATE
            ),
            "coverage_before": before.model_dump(mode="json"),
            "coverage_projected": projected.model_dump(mode="json"),
        }
        report["report_fingerprint"] = report_fingerprint(report)
        return report


async def preview_spatial_reenrichment(
    store: ReenrichmentStore,
    projector: SpatialProjector,
    job: ReenrichmentJob,
) -> dict[str, Any]:
    """Produce one complete full-lane report without any mutation capability."""

    return await _run_spatial_reenrichment(
        store,
        projector,
        None,
        job,
        mode=_ReenrichmentMode.DRY_RUN,
        checkpoint=Checkpoint(),
        approved_report_fingerprint=None,
    )


async def apply_spatial_reenrichment(
    store: ReenrichmentStore,
    projector: SpatialProjector,
    checkpoints: CheckpointStore,
    job: ReenrichmentJob,
    *,
    approved_report: Mapping[str, object],
) -> dict[str, Any]:
    """Apply only a reviewed full-lane dry-run, preserving approval on resume."""

    approved_fingerprint = _validated_dry_run_fingerprint(
        "approved",
        approved_report,
    )
    checkpoint = checkpoints.load(job)
    if checkpoint.approved_report_fingerprint is None:
        fresh = await preview_spatial_reenrichment(store, projector, job)
        validate_dry_run_approval(approved_report, fresh)
    elif checkpoint.approved_report_fingerprint != approved_fingerprint:
        raise ValueError("approved dry-run does not match the durable checkpoint")
    return await _run_spatial_reenrichment(
        store,
        projector,
        checkpoints,
        job,
        mode=_ReenrichmentMode.APPLY,
        checkpoint=checkpoint,
        approved_report_fingerprint=approved_fingerprint,
    )


async def _run_spatial_reenrichment(
    store: ReenrichmentStore,
    projector: SpatialProjector,
    checkpoints: CheckpointStore | None,
    job: ReenrichmentJob,
    *,
    mode: _ReenrichmentMode,
    checkpoint: Checkpoint,
    approved_report_fingerprint: str | None,
) -> dict[str, Any]:
    """Internal runner; checkpoint only fully confirmed apply pages."""

    report = _Report(
        job=job,
        mode=mode,
        start_cursor=checkpoint.cursor,
        end_cursor=checkpoint.cursor,
    )
    if checkpoint.complete:
        report.complete = True
        return report.to_dict()

    cursor = checkpoint.cursor
    while True:
        page = await store.fetch_page(job.lane, cursor, job.batch_size)
        _validate_page(page, cursor=cursor, limit=job.batch_size)
        if not page.points:
            report.complete = True
            report.end_cursor = page.next_cursor
            if mode is _ReenrichmentMode.APPLY:
                if checkpoints is None or approved_report_fingerprint is None:
                    raise RuntimeError("apply execution is missing approval state")
                checkpoints.save(
                    job,
                    Checkpoint(
                        cursor=page.next_cursor,
                        complete=True,
                        approved_report_fingerprint=approved_report_fingerprint,
                    ),
                )
            break

        replacements: list[ReenrichmentPoint] = []
        for point in page.points:
            report.total_points += 1
            report.coverage_before.observe(
                point.payload,
                job.target_projection_revision,
            )
            projected = _replacement(point, projector.project(point, job), job)
            report.coverage_projected.observe(
                projected.payload,
                job.target_projection_revision,
            )
            if projected.payload == point.payload:
                report.already_current += 1
            else:
                replacements.append(projected)

        report.writes_planned += len(replacements)
        if mode is _ReenrichmentMode.APPLY and replacements:
            written = await store.replace_points(job.lane, replacements)
            if written != len(replacements):
                raise RuntimeError(
                    f"Qdrant spatial batch replaced {written} of {len(replacements)} points"
                )
            report.writes_applied += written

        report.batches_completed += 1
        cursor = page.next_cursor
        report.end_cursor = cursor
        report.complete = cursor is None
        if mode is _ReenrichmentMode.APPLY:
            if checkpoints is None or approved_report_fingerprint is None:
                raise RuntimeError("apply execution is missing approval state")
            checkpoints.save(
                job,
                Checkpoint(
                    cursor=cursor,
                    complete=report.complete,
                    approved_report_fingerprint=approved_report_fingerprint,
                ),
            )
        if report.complete:
            break

    return report.to_dict()


def plan_spatial_reenrichment_jobs(
    previous_scope_derivation_revisions: Mapping[str, str],
    current_scope_derivation_revisions: Mapping[str, str],
    *,
    lanes: Sequence[str],
    previous_projection_revision: str | None = None,
    batch_size: int = 500,
) -> tuple[ReenrichmentJob, ...]:
    """Schedule each lane only when complete projection semantics changed."""

    target = derive_spatial_projection_revision(current_scope_derivation_revisions)
    previous = previous_projection_revision
    if previous is None and previous_scope_derivation_revisions:
        previous = derive_spatial_projection_revision(
            previous_scope_derivation_revisions
        )
    if previous == target:
        return ()
    return tuple(
        ReenrichmentJob(
            lane=lane,
            target_projection_revision=target,
            batch_size=batch_size,
        )
        for lane in sorted(set(lanes))
    )


def report_fingerprint(report: Mapping[str, object]) -> str:
    """Hash a canonical report excluding its self-referential fingerprint."""

    payload = {
        key: value for key, value in report.items() if key != "report_fingerprint"
    }
    return hashlib.sha256(_canonical_json(payload).encode("ascii")).hexdigest()


def validate_dry_run_approval(
    approved_report: Mapping[str, object],
    fresh_dry_run: Mapping[str, object],
) -> None:
    """Require a complete, unchanged full-lane dry-run before an operator apply."""

    approved_fingerprint = _validated_dry_run_fingerprint(
        "approved",
        approved_report,
    )
    fresh_fingerprint = _validated_dry_run_fingerprint("fresh", fresh_dry_run)
    if approved_fingerprint != fresh_fingerprint:
        raise ValueError("approved dry-run drifted from the current Qdrant lane")


def publish_spatial_coverage_snapshot(
    path: Path,
    reports: Sequence[Mapping[str, object]],
) -> SpatialCoverageSnapshotV1:
    """Atomically publish coverage from verified, current full-index scans.

    Callers run one fresh preview per lane after re-enrichment.  Projected
    dry-run counts are deliberately rejected: only ``coverage_before`` proves
    what is currently stored and therefore filterable in Qdrant.
    """

    lanes: list[SpatialLaneCoverageV1] = []
    target_revision: str | None = None
    for report in reports:
        _validated_dry_run_fingerprint("coverage", report)
        if report.get("writes_planned") != 0 or (
            report.get("coverage_before") != report.get("coverage_projected")
        ):
            raise ValueError(
                "coverage report does not describe current index coverage"
            )
        before = SpatialCoverageSnapshotV1.model_validate_json(
            _canonical_json(report.get("coverage_before"))
        )
        if len(before.lanes) != 1:
            raise ValueError("coverage report must describe exactly one lane")
        job = report.get("job")
        if not isinstance(job, Mapping):
            raise ValueError("coverage report job is invalid")
        lane = before.lanes[0]
        if (
            job.get("lane") != lane.lane
            or job.get("target_projection_revision")
            != before.target_projection_revision
        ):
            raise ValueError("coverage report identity does not match its job")
        if target_revision is None:
            target_revision = before.target_projection_revision
        elif target_revision != before.target_projection_revision:
            raise ValueError("coverage lanes target different projection revisions")
        lanes.append(lane)

    if target_revision is None:
        raise ValueError("at least one Qdrant coverage report is required")
    lanes.sort(key=lambda lane: lane.lane)
    snapshot = SpatialCoverageSnapshotV1(
        target_projection_revision=target_revision,
        lanes=tuple(lanes),
    )
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError("coverage snapshot path must be a regular file")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as temporary:
        temporary.write(_canonical_json(snapshot.model_dump(mode="json")))
        temporary_path = Path(temporary.name)
    temporary_path.replace(path)
    return snapshot


def _validated_dry_run_fingerprint(
    label: str,
    report: Mapping[str, object],
) -> str:
    if report.get("mode") != _ReenrichmentMode.DRY_RUN.value:
        raise ValueError(f"{label} report is not a dry-run")
    if report.get("complete") is not True or report.get("start_cursor") is not None:
        raise ValueError(f"{label} dry-run is not a complete full-lane scan")
    fingerprint = report.get("report_fingerprint")
    if not isinstance(fingerprint, str) or fingerprint != report_fingerprint(report):
        if label == "fresh":
            raise ValueError("fresh dry-run drifted from its fingerprint")
        raise ValueError("approved dry-run fingerprint is invalid")
    return fingerprint


def _replacement(
    point: ReenrichmentPoint,
    projection: Mapping[str, object],
    job: ReenrichmentJob,
) -> ReenrichmentPoint:
    projected = _validated_projection(projection, job)
    # ``geo`` is projection-owned, but omission is not a clear operation.  A
    # projector must return ``geo: null`` explicitly to remove an existing
    # coordinate; otherwise a full-point upsert preserves the last good value.
    if "geo" not in projected and "geo" in point.payload:
        projected["geo"] = point.payload["geo"]
    preserved = {
        key: value
        for key, value in point.payload.items()
        if not _projection_owned(key)
    }
    preserved.update(projected)
    return ReenrichmentPoint(
        point_id=point.point_id,
        vector=point.vector,
        payload=preserved,
    )


def _validated_projection(
    projection: Mapping[str, object],
    job: ReenrichmentJob,
) -> dict[str, object]:
    if not isinstance(projection, Mapping) or not all(
        isinstance(key, str) for key in projection
    ):
        raise ValueError("spatial projector must return a string-keyed mapping")
    proposed = dict(projection)
    unexpected = sorted(key for key in proposed if not _projection_owned(key))
    if unexpected:
        raise ValueError(f"projector returned non-spatial fields: {unexpected}")
    missing = sorted(_REQUIRED_PROJECTION_FIELDS - proposed.keys())
    if missing:
        raise ValueError(f"projector omitted required spatial fields: {missing}")
    if "spatial_derivation_revision" in proposed:
        raise ValueError("Qdrant projection must not contain a scalar derivation revision")
    if proposed["spatial_projection_revision"] != job.target_projection_revision:
        raise ValueError("projector target revision does not match re-enrichment job")
    if proposed["spatial_derivation_version"] != SPATIAL_DERIVATION_VERSION:
        raise ValueError("projector derivation version is incompatible")

    token_count = 0
    for token_field in _TOKEN_FIELDS:
        tokens = proposed[token_field]
        if not isinstance(tokens, list) or not all(
            isinstance(token, str) and _valid_pair_token(token) for token in tokens
        ):
            raise ValueError(f"invalid pair-token array: {token_field}")
        if len(tokens) != len(set(tokens)) or tokens != sorted(tokens):
            raise ValueError(
                f"pair-token array must be unique and sorted: {token_field}"
            )
        token_count += len(tokens)

    conflict = proposed["spatial_conflict"]
    status = proposed["spatial_derivation_status"]
    if not isinstance(conflict, bool) or status not in {
        "filterable",
        "conflict",
        "audit_only",
        "unavailable",
    }:
        raise ValueError("invalid spatial derivation status")
    if status == "filterable" and token_count == 0:
        raise ValueError("filterable projection requires pair tokens")
    if status == "conflict" and (not conflict or token_count != 0):
        raise ValueError("conflict projection must suppress pair tokens")
    if status in {"audit_only", "unavailable"} and (conflict or token_count != 0):
        raise ValueError("non-filterable projection must suppress pair tokens")
    if conflict and status not in {"filterable", "conflict"}:
        raise ValueError("spatial conflict and derivation status disagree")

    conflict_keys = proposed["spatial_conflict_scope_keys"]
    if not isinstance(conflict_keys, list) or not all(
        isinstance(scope_key, str) for scope_key in conflict_keys
    ):
        raise ValueError("invalid spatial conflict scope keys")
    if conflict_keys != sorted(set(conflict_keys)):
        raise ValueError("spatial conflict scope keys must be unique and sorted")
    if not isinstance(proposed["spatial_basis"], list):
        raise ValueError("spatial basis must be an array")
    if not isinstance(proposed["spatial_derivations"], list):
        raise ValueError("spatial derivations must be an array")
    if "geo" in proposed:
        _validate_geo(proposed["geo"])
    return proposed


def _coverage_status(
    payload: Mapping[str, object],
    target_revision: str,
) -> str:
    status = payload.get("spatial_derivation_status")
    has_tokens = any(
        isinstance(payload.get(field), list) and bool(payload[field])
        for field in _TOKEN_FIELDS
    )
    conflict = payload.get("spatial_conflict") is True
    if status == "unavailable":
        return "inconsistent" if has_tokens or conflict else "unsupported"
    revision = payload.get("spatial_projection_revision")
    if revision is None:
        return "unprojected"
    if revision != target_revision:
        return "stale"
    if status == "filterable":
        return "filterable" if has_tokens else "inconsistent"
    if status == "conflict":
        return "conflict" if conflict and not has_tokens else "inconsistent"
    if status == "audit_only":
        return "audit_only" if not conflict and not has_tokens else "inconsistent"
    return "inconsistent"


def _coverage_snapshot(
    job: ReenrichmentJob,
    coverage: _Coverage,
) -> SpatialCoverageSnapshotV1:
    return SpatialCoverageSnapshotV1(
        target_projection_revision=job.target_projection_revision,
        lanes=(coverage.snapshot(job.lane),),
    )


def _projection_owned(field: str) -> bool:
    return field.startswith("spatial_") or field in _RAW_SPATIAL_FIELDS


def _valid_pair_token(token: str) -> bool:
    parts = token.split("|")
    if len(parts) != 3 or parts[0] != "sr1":
        return False
    try:
        return encode_scope_revision_token(parts[1], parts[2]) == token
    except ValueError:
        return False


def _validate_geo(value: object) -> None:
    if value is None:
        return
    points = value if isinstance(value, list) else [value]
    if not points:
        raise ValueError("geo projection must not be empty")
    for point in points:
        if not isinstance(point, dict) or set(point) != {"lon", "lat"}:
            raise ValueError("geo projection must contain lon/lat points")
        lon = point["lon"]
        lat = point["lat"]
        if (
            not isinstance(lon, int | float)
            or isinstance(lon, bool)
            or not isinstance(lat, int | float)
            or isinstance(lat, bool)
            or not math.isfinite(lon)
            or not math.isfinite(lat)
            or not -180 <= lon <= 180
            or not -90 <= lat <= 90
        ):
            raise ValueError("geo projection coordinates are invalid")


def _validate_page(page: ReenrichmentPage, *, cursor: Cursor, limit: int) -> None:
    if not isinstance(page, ReenrichmentPage):
        raise TypeError("re-enrichment store returned an invalid page")
    if len(page.points) > limit:
        raise RuntimeError("Qdrant re-enrichment page exceeds requested limit")
    identifiers = [point.point_id for point in page.points]
    if len(identifiers) != len(set(identifiers)):
        raise RuntimeError("Qdrant re-enrichment page contains duplicate point IDs")
    if page.points and page.next_cursor is not None and page.next_cursor == cursor:
        raise RuntimeError("Qdrant re-enrichment cursor did not advance")
    if not page.points and page.next_cursor is not None:
        raise RuntimeError("empty Qdrant page must terminate the scroll")


def _valid_cursor(cursor: object) -> bool:
    return cursor is None or (
        isinstance(cursor, str | int) and not isinstance(cursor, bool)
    )


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _promotion_stale_rate(coverage: _Coverage) -> float:
    """Treat absent current projections as stale for promotion purposes."""

    return _ratio(
        (
            coverage.stale_points
            + coverage.unprojected_points
            + coverage.inconsistent_points
        ),
        coverage.total_points,
    )


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


__all__ = [
    "Checkpoint",
    "CheckpointStore",
    "JsonCheckpointStore",
    "MemoryCheckpointStore",
    "QdrantReenrichmentStore",
    "ReenrichmentJob",
    "ReenrichmentPage",
    "ReenrichmentPoint",
    "ReenrichmentStore",
    "SpatialProjector",
    "apply_spatial_reenrichment",
    "plan_spatial_reenrichment_jobs",
    "preview_spatial_reenrichment",
    "publish_spatial_coverage_snapshot",
    "report_fingerprint",
    "validate_dry_run_approval",
]
