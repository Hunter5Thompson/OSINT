from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
import polars as pl
import pytest

from gdelt_raw.recovery import replay_pending
from gdelt_raw.state import GDELTState


@pytest.mark.asyncio
async def test_pending_store_replay_from_parquet(tmp_path):
    """Slice S was parquet-done but neo4j failed. Replay must succeed
    without re-downloading."""
    # Create parquet fixtures for slice 20260425120000 date=2026-04-25
    slice_id = "20260425120000"
    date = "2026-04-25"
    for stream, df in [
        ("events", pl.DataFrame({"event_id": ["gdelt:event:1"]})),
        ("gkg", pl.DataFrame({"doc_id": ["gdelt:gkg:r1"]})),
        ("mentions", pl.DataFrame({"event_id": ["gdelt:event:1"]})),
    ]:
        p = tmp_path / stream / f"date={date}"
        p.mkdir(parents=True)
        df.write_parquet(p / f"{slice_id}.parquet")

    # Setup state: parquet done, neo4j pending
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    state = GDELTState(r)
    for st in ("events", "gkg", "mentions"):
        await state.set_stream_parquet(slice_id, st, "done")
    await state.set_store_state(slice_id, "neo4j", "pending")
    await state.add_pending("neo4j", slice_id)

    neo4j = MagicMock()
    neo4j.write_from_parquet = AsyncMock()
    qdrant = MagicMock()
    qdrant.upsert_from_parquet = AsyncMock(return_value=0)

    await replay_pending(state, parquet_base=tmp_path, neo4j_writer=neo4j,
                        qdrant_writer=qdrant)

    neo4j.write_from_parquet.assert_awaited_once()
    assert await state.get_store_state(slice_id, "neo4j") == "done"
    assert slice_id not in await state.list_pending("neo4j")


@pytest.mark.asyncio
async def test_qdrant_recovery_independent_of_neo4j(tmp_path):
    """Qdrant can replay even if Neo4j is still pending."""
    slice_id = "20260425120000"
    date = "2026-04-25"
    p = tmp_path / "gkg" / f"date={date}"
    p.mkdir(parents=True)
    pl.DataFrame({"doc_id": ["gdelt:gkg:r1"]}).write_parquet(p / f"{slice_id}.parquet")

    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    state = GDELTState(r)
    await state.set_stream_parquet(slice_id, "gkg", "done")
    await state.set_store_state(slice_id, "qdrant", "pending_embed")
    await state.add_pending("qdrant", slice_id)
    # Leave neo4j unresolved on purpose

    neo4j = MagicMock(); neo4j.write_from_parquet = AsyncMock()
    qdrant = MagicMock()
    qdrant.upsert_from_parquet = AsyncMock(return_value=1)

    await replay_pending(state, parquet_base=tmp_path, neo4j_writer=neo4j,
                        qdrant_writer=qdrant)
    qdrant.upsert_from_parquet.assert_awaited_once()
    assert await state.get_store_state(slice_id, "qdrant") == "done"
