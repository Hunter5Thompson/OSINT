"""Tests for GDELT backfill flow (resumable, parallel)."""

from datetime import datetime
from unittest.mock import AsyncMock  # noqa: F401  (kept per plan)

import fakeredis.aioredis
import pytest

from gdelt_raw.run import (
    enumerate_slices_for_range,
    initialize_backfill,
    mark_slice_done,
    mark_slice_failed,
)
from gdelt_raw.state import GDELTState


def test_enumerate_slices_full_day():
    slices = list(enumerate_slices_for_range(
        datetime(2026, 4, 25), datetime(2026, 4, 25, 23, 45)
    ))
    assert slices[0] == "20260425000000"
    assert slices[-1] == "20260425234500"
    assert len(slices) == 96


def test_enumerate_slices_partial():
    slices = list(enumerate_slices_for_range(
        datetime(2026, 4, 25, 0, 0), datetime(2026, 4, 25, 1, 0)
    ))
    assert slices == [
        "20260425000000", "20260425001500", "20260425003000",
        "20260425004500", "20260425010000",
    ]


def test_enumerate_slices_31_days():
    slices = list(enumerate_slices_for_range(
        datetime(2026, 3, 26), datetime(2026, 4, 25, 23, 45)
    ))
    assert len(slices) == 31 * 96


@pytest.mark.asyncio
async def test_backfill_initializes_pending_set():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    state = GDELTState(r)
    job = await initialize_backfill(
        state, job_id="job-a",
        start=datetime(2026, 4, 25, 0, 0),
        end=datetime(2026, 4, 25, 1, 0),
    )
    assert job.job_id == "job-a"
    assert job.total == 5
    pending = await r.zrange("gdelt:backfill:job-a:pending", 0, -1)
    assert len(pending) == 5


@pytest.mark.asyncio
async def test_backfill_marks_slice_done_removes_from_pending():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    state = GDELTState(r)
    await initialize_backfill(
        state, job_id="job-b",
        start=datetime(2026, 4, 25, 0, 0),
        end=datetime(2026, 4, 25, 0, 0),
    )
    await mark_slice_done(state, "job-b", "20260425000000")
    pending = await r.zrange("gdelt:backfill:job-b:pending", 0, -1)
    done = await r.smembers("gdelt:backfill:job-b:done")
    assert pending == []
    assert done == {"20260425000000"}


@pytest.mark.asyncio
async def test_backfill_failed_slice_is_retryable():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    state = GDELTState(r)
    await initialize_backfill(
        state, job_id="job-c",
        start=datetime(2026, 4, 25, 0, 0),
        end=datetime(2026, 4, 25, 0, 0),
    )
    await mark_slice_failed(state, "job-c", "20260425000000", reason="boom")
    # Failed slices move to :failed AND remain re-enqueueable via resume
    failed = await r.smembers("gdelt:backfill:job-c:failed")
    assert "20260425000000" in failed


@pytest.mark.asyncio
async def test_resume_reenqueues_failed_slices():
    from gdelt_raw.run import resume_backfill_pending
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    state = GDELTState(r)
    await initialize_backfill(
        state, job_id="job-d",
        start=datetime(2026, 4, 25, 0, 0),
        end=datetime(2026, 4, 25, 0, 30),
    )
    await mark_slice_done(state, "job-d", "20260425000000")
    await mark_slice_failed(state, "job-d", "20260425001500", reason="net")
    # Pending now contains only 20260425003000
    await resume_backfill_pending(state, "job-d")
    # After resume, failed is empty and pending contains the retry
    pending = await r.zrange("gdelt:backfill:job-d:pending", 0, -1)
    assert "20260425001500" in pending
    assert await r.smembers("gdelt:backfill:job-d:failed") == set()
