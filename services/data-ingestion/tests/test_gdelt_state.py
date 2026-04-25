import fakeredis.aioredis
import pytest

from gdelt_raw.state import GDELTState


@pytest.fixture
def state():
    # asyncio_mode=auto auto-resolves async fixtures before injection, so we
    # use a regular fixture returning a fresh FakeRedis-backed state per test.
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return GDELTState(r)


@pytest.mark.asyncio
async def test_stream_state_roundtrip(state):
    await state.set_stream_parquet("20260425120000", "events", "done")
    assert await state.get_stream_parquet("20260425120000", "events") == "done"


@pytest.mark.asyncio
async def test_store_state_transition(state):
    await state.set_store_state("20260425120000", "neo4j", "pending")
    await state.add_pending("neo4j", "20260425120000")
    assert "20260425120000" in await state.list_pending("neo4j")
    await state.set_store_state("20260425120000", "neo4j", "done")
    await state.remove_pending("neo4j", "20260425120000")
    assert "20260425120000" not in await state.list_pending("neo4j")


@pytest.mark.asyncio
async def test_summary_last_slice(state):
    await state.set_last_slice("neo4j", "20260425120000")
    assert await state.get_last_slice("neo4j") == "20260425120000"


@pytest.mark.asyncio
async def test_slice_is_fully_done_requires_all_three_streams_plus_stores(state):
    # Only one stream done — not fully done
    await state.set_stream_parquet("20260425120000", "events", "done")
    assert not await state.is_slice_fully_done("20260425120000")
    # All three plus both stores → done
    await state.set_stream_parquet("20260425120000", "gkg", "done")
    await state.set_stream_parquet("20260425120000", "mentions", "done")
    await state.set_store_state("20260425120000", "neo4j", "done")
    await state.set_store_state("20260425120000", "qdrant", "done")
    assert await state.is_slice_fully_done("20260425120000")
