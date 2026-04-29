"""Tests for check_ingestion_llm() — three exclusive outcomes."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import structlog


def test_scheduler_registers_only_gdelt_raw_forward_job():
    """Legacy DOC-API GDELT collector must stay out of the production schedule."""
    from scheduler import create_scheduler

    scheduler = create_scheduler()
    job_ids = {job.id for job in scheduler.get_jobs()}
    job_names = {job.name for job in scheduler.get_jobs()}

    assert "gdelt_raw_forward" in job_ids
    assert "GDELT Raw Files Forward Collector" in job_names
    assert "gdelt_collector" not in job_ids
    assert "GDELT Event Collector" not in job_names


@pytest.mark.asyncio
async def test_ready_when_model_in_response():
    """200 + model in data[].id → log 'ingestion_llm_ready'."""
    from scheduler import check_ingestion_llm

    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"data": [
        {"id": "Qwen/Qwen3.6-35B-A3B"},
        {"id": "other/model"},
    ]}

    with patch("scheduler.httpx.AsyncClient") as mock_cls:
        mc = AsyncMock()
        mc.get.return_value = resp
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mc)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with structlog.testing.capture_logs() as cap:
            await check_ingestion_llm()

    assert any(entry.get("event") == "ingestion_llm_ready" for entry in cap)


@pytest.mark.asyncio
async def test_model_mismatch_logs_error():
    """200 + model NOT in data[].id → log 'ingestion_llm_model_mismatch'."""
    from scheduler import check_ingestion_llm

    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"data": [{"id": "wrong/model"}]}

    with patch("scheduler.httpx.AsyncClient") as mock_cls:
        mc = AsyncMock()
        mc.get.return_value = resp
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mc)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with structlog.testing.capture_logs() as cap:
            await check_ingestion_llm()

    assert any(entry.get("event") == "ingestion_llm_model_mismatch" for entry in cap)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 404])
async def test_4xx_logs_config_error(status):
    """401/403/404 on /v1/models → log 'ingestion_llm_config_error'."""
    from scheduler import check_ingestion_llm

    bad = MagicMock()
    bad.status_code = status
    bad.raise_for_status.side_effect = httpx.HTTPStatusError(
        str(status), request=MagicMock(), response=MagicMock(status_code=status)
    )

    with patch("scheduler.httpx.AsyncClient") as mock_cls:
        mc = AsyncMock()
        mc.get.return_value = bad
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mc)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with structlog.testing.capture_logs() as cap:
            await check_ingestion_llm()

    assert any(entry.get("event") == "ingestion_llm_config_error" for entry in cap)


@pytest.mark.asyncio
@pytest.mark.parametrize("exc", [
    httpx.ConnectError("refused"),
    httpx.TimeoutException("slow"),
    httpx.ReadTimeout("slow read"),
])
async def test_transient_exceptions_log_unreachable(exc):
    """ConnectError, Timeout, ReadTimeout → log 'ingestion_llm_unreachable'."""
    from scheduler import check_ingestion_llm

    with patch("scheduler.httpx.AsyncClient") as mock_cls:
        mc = AsyncMock()
        mc.get.side_effect = exc
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mc)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with structlog.testing.capture_logs() as cap:
            await check_ingestion_llm()

    assert any(entry.get("event") == "ingestion_llm_unreachable" for entry in cap)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [500, 502, 503])
async def test_5xx_logs_unreachable(status):
    """5xx on /v1/models → log 'ingestion_llm_unreachable' (NOT config_error)."""
    from scheduler import check_ingestion_llm

    bad = MagicMock()
    bad.status_code = status
    bad.raise_for_status.side_effect = httpx.HTTPStatusError(
        str(status), request=MagicMock(), response=MagicMock(status_code=status)
    )

    with patch("scheduler.httpx.AsyncClient") as mock_cls:
        mc = AsyncMock()
        mc.get.return_value = bad
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mc)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with structlog.testing.capture_logs() as cap:
            await check_ingestion_llm()

    assert any(entry.get("event") == "ingestion_llm_unreachable" for entry in cap)
    # Must NOT log config_error for 5xx.
    assert not any(entry.get("event") == "ingestion_llm_config_error" for entry in cap)


@pytest.mark.asyncio
async def test_check_never_raises():
    """check_ingestion_llm() never raises — scheduler must always start."""
    from scheduler import check_ingestion_llm

    with patch("scheduler.httpx.AsyncClient", side_effect=Exception("anything")):
        # Must not raise.
        await check_ingestion_llm()
