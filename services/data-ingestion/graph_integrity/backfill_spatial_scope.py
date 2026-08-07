"""Initial Spatial Scope backfill built on the shared restartable batch engine."""

from __future__ import annotations

from typing import Any

from graph_integrity.spatial_batch import (
    BatchJob,
    CheckpointStore,
    SpatialBatchClient,
    run_spatial_batch,
)
from graph_integrity.spatial_normalizer import SpatialNormalizationIndex


async def run(
    client: SpatialBatchClient,
    spatial_index: SpatialNormalizationIndex,
    checkpoints: CheckpointStore,
    *,
    lane: str,
    target_derivation_revision: str,
    batch_size: int = 500,
    dry_run: bool,
) -> dict[str, Any]:
    """Backfill one source lane at one explicitly reviewed target revision."""

    job = BatchJob(
        "backfill",
        lane,
        target_derivation_revision,
        batch_size=batch_size,
    )
    return await run_spatial_batch(
        client,
        spatial_index,
        checkpoints,
        job,
        dry_run=dry_run,
    )
