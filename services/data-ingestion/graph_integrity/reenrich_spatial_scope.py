"""Revision-aware scheduling for recurring Spatial Scope re-enrichment."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from graph_integrity.spatial_batch import (
    BatchJob,
    CheckpointStore,
    SpatialBatchClient,
    report_fingerprint,
    run_spatial_batch,
)
from graph_integrity.spatial_normalizer import SpatialNormalizationIndex
from spatial_catalog.identity import parse_scope_key
from spatial_catalog.models import ScopeKind

_LANE_SCOPE_KINDS = {
    "sensor_observation": frozenset({ScopeKind.COUNTRY, ScopeKind.ADMIN1, ScopeKind.ADMIN2}),
    "backend_incident": frozenset({ScopeKind.COUNTRY, ScopeKind.ADMIN1, ScopeKind.ADMIN2}),
    "gdelt_raw": frozenset({ScopeKind.COUNTRY, ScopeKind.ADMIN1, ScopeKind.ADMIN2}),
    "military_aircraft": frozenset({ScopeKind.COUNTRY, ScopeKind.ADMIN1, ScopeKind.ADMIN2}),
    "rss_pipeline": frozenset({ScopeKind.COUNTRY}),
}


def plan_reenrichment_jobs(
    previous_revisions: Mapping[str, str],
    current_revisions: Mapping[str, str],
    *,
    lanes: Sequence[str] = tuple(_LANE_SCOPE_KINDS),
    batch_size: int = 500,
) -> tuple[BatchJob, ...]:
    """Create one restartable scan per lane for actual derivation changes."""

    unknown_lanes = set(lanes) - set(_LANE_SCOPE_KINDS)
    if unknown_lanes:
        raise ValueError(f"unsupported re-enrichment lanes: {sorted(unknown_lanes)}")

    changed = {
        key: revision
        for key, revision in current_revisions.items()
        if previous_revisions.get(key) != revision
    }
    jobs: list[BatchJob] = []
    for lane in sorted(set(lanes)):
        affected = tuple(
            sorted(
                (key, revision)
                for key, revision in changed.items()
                if parse_scope_key(key).kind in _LANE_SCOPE_KINDS[lane]
            )
        )
        if affected:
            jobs.append(
                BatchJob(
                    "reenrichment",
                    lane,
                    None,
                    batch_size=batch_size,
                    target_scope_keys=tuple(key for key, _ in affected),
                    target_scope_revisions=affected,
                )
            )
    return tuple(jobs)


def derivation_revision_map(
    spatial_index: SpatialNormalizationIndex,
) -> dict[str, str]:
    """Expose the immutable scope/revision map needed for catalog comparison."""

    return {
        scope_key: record.derivation_revision for scope_key, record in spatial_index.scopes.items()
    }


async def run_jobs(
    client: SpatialBatchClient,
    spatial_index: SpatialNormalizationIndex,
    checkpoints: CheckpointStore,
    jobs: Sequence[BatchJob],
    *,
    dry_run: bool,
) -> dict[str, Any]:
    """Run planned jobs and return one deterministic machine-readable envelope."""

    reports = [
        await run_spatial_batch(
            client,
            spatial_index,
            checkpoints,
            job,
            dry_run=dry_run,
        )
        for job in jobs
    ]
    envelope: dict[str, Any] = {
        "schema_version": 1,
        "mode": "dry-run" if dry_run else "apply",
        "catalog_revision": spatial_index.catalog_revision,
        "job_count": len(reports),
        "complete": all(report["complete"] for report in reports),
        "jobs": reports,
        "totals": {
            field: sum(int(report[field]) for report in reports)
            for field in (
                "total",
                "already_normalized",
                "resolvable",
                "unresolved",
                "conflict",
                "invalid_coordinate",
                "target_revision_mismatch",
                "writes_planned",
                "writes_applied",
            )
        },
    }
    envelope["report_fingerprint"] = report_fingerprint(envelope)
    return envelope
