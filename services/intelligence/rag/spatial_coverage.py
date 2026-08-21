"""Validated Qdrant index-build coverage consumed by scoped retrieval."""

from __future__ import annotations

from collections.abc import Collection
from pathlib import Path

from config import settings
from spatial import SpatialCoverageSnapshotV1


def load_spatial_coverage_snapshot(
    path: Path,
) -> SpatialCoverageSnapshotV1 | None:
    """Load the immutable snapshot emitted by the index/re-enrichment build."""

    if not path.is_file():
        return None
    return SpatialCoverageSnapshotV1.model_validate_json(path.read_bytes())


def get_spatial_coverage_snapshot() -> SpatialCoverageSnapshotV1 | None:
    return load_spatial_coverage_snapshot(settings.spatial_coverage_snapshot_path)


def coverage_is_complete(
    snapshot: SpatialCoverageSnapshotV1,
    *,
    required_lanes: Collection[str],
) -> bool:
    """True only when every queried lane is present, current and filterable."""

    lanes = {lane.lane: lane for lane in snapshot.lanes}
    required = set(required_lanes)
    return bool(required) and required.issubset(lanes) and all(
        lanes[name].total_points > 0
        and lanes[name].filterable_points == lanes[name].total_points
        for name in required
    )


__all__ = [
    "coverage_is_complete",
    "get_spatial_coverage_snapshot",
    "load_spatial_coverage_snapshot",
]
