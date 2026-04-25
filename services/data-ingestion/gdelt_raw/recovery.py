"""Pending-replay: re-hydrate Neo4j and Qdrant from Parquet.

Neo4j and Qdrant replay independently — Qdrant never blocks on Neo4j.
"""

from __future__ import annotations

from pathlib import Path

import structlog

from gdelt_raw.state import GDELTState

log = structlog.get_logger(__name__)


def _slice_date(slice_id: str) -> str:
    # 20260425120000 → 2026-04-25
    return f"{slice_id[0:4]}-{slice_id[4:6]}-{slice_id[6:8]}"


def _parquet_exists(parquet_base: Path, stream: str, slice_id: str) -> bool:
    p = parquet_base / stream / f"date={_slice_date(slice_id)}" / f"{slice_id}.parquet"
    return p.exists()


async def replay_pending(
    state: GDELTState,
    *,
    parquet_base: Path,
    neo4j_writer,
    qdrant_writer,
    limit: int = 10,
) -> None:
    # Neo4j recovery — needs all three parquet streams
    for slice_id in await state.list_pending("neo4j", limit=limit):
        if not all(_parquet_exists(parquet_base, s, slice_id)
                   for s in ("events", "gkg", "mentions")):
            log.info("neo4j_recovery_skipped_parquet_missing", slice=slice_id)
            continue
        try:
            await neo4j_writer.write_from_parquet(
                parquet_base, slice_id, _slice_date(slice_id))
            await state.set_store_state(slice_id, "neo4j", "done")
            await state.remove_pending("neo4j", slice_id)
            log.info("neo4j_recovery_done", slice=slice_id)
        except Exception as e:
            log.error("neo4j_recovery_retry_failed", slice=slice_id, error=str(e))

    # Qdrant recovery — needs only GKG parquet
    for slice_id in await state.list_pending("qdrant", limit=limit):
        if not _parquet_exists(parquet_base, "gkg", slice_id):
            log.info("qdrant_recovery_skipped_parquet_missing", slice=slice_id)
            continue
        try:
            await qdrant_writer.upsert_from_parquet(
                parquet_base, slice_id, _slice_date(slice_id))
            await state.set_store_state(slice_id, "qdrant", "done")
            await state.remove_pending("qdrant", slice_id)
            log.info("qdrant_recovery_done", slice=slice_id)
        except Exception as e:
            log.error("qdrant_recovery_retry_failed", slice=slice_id, error=str(e))
