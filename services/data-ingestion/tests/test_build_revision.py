"""The scheduler identifies the code loaded at process startup."""

from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog

import scheduler


@pytest.mark.asyncio
@pytest.mark.parametrize("revision", [None, "a" * 40])
async def test_scheduler_logs_loaded_revision_before_any_collection(monkeypatch, revision):
    monkeypatch.setenv("ODIN_BUILD_REVISION", "b" * 40)
    monkeypatch.setattr(scheduler, "BUILD_REVISION", revision, raising=False)
    monkeypatch.setattr(scheduler, "create_scheduler", MagicMock())
    monkeypatch.setattr(scheduler.signal, "signal", MagicMock())
    monkeypatch.setattr(scheduler, "check_ingestion_llm", AsyncMock())
    monkeypatch.setattr(scheduler, "initial_collection_jobs", lambda: [])
    monkeypatch.setattr(scheduler, "_redis_client", None)
    monkeypatch.setattr(scheduler.asyncio, "Event", lambda: AsyncMock())

    with structlog.testing.capture_logs() as entries:
        await scheduler.main()

    assert entries[0]["event"] == "scheduler_starting"
    assert entries[0]["revision"] == revision
    running = next(entry for entry in entries if entry["event"] == "scheduler_running")
    assert running["revision"] == revision
