"""Tests for check_ingestion_llm() — three exclusive outcomes."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


@pytest.mark.asyncio
async def test_ready_when_model_in_response(caplog):
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

        with caplog.at_level("INFO"):
            await check_ingestion_llm()

    assert any("ingestion_llm_ready" in rec.getMessage() for rec in caplog.records)


@pytest.mark.asyncio
async def test_model_mismatch_logs_error(caplog):
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

        with caplog.at_level("ERROR"):
            await check_ingestion_llm()

    assert any("ingestion_llm_model_mismatch" in rec.getMessage() for rec in caplog.records)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 404])
async def test_4xx_logs_config_error(status, caplog):
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

        with caplog.at_level("ERROR"):
            await check_ingestion_llm()

    assert any("ingestion_llm_config_error" in rec.getMessage() for rec in caplog.records)


@pytest.mark.asyncio
@pytest.mark.parametrize("exc", [
    httpx.ConnectError("refused"),
    httpx.TimeoutException("slow"),
    httpx.ReadTimeout("slow read"),
])
async def test_transient_exceptions_log_unreachable(exc, caplog):
    """ConnectError, Timeout, ReadTimeout → log 'ingestion_llm_unreachable'."""
    from scheduler import check_ingestion_llm

    with patch("scheduler.httpx.AsyncClient") as mock_cls:
        mc = AsyncMock()
        mc.get.side_effect = exc
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mc)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with caplog.at_level("WARNING"):
            await check_ingestion_llm()

    assert any("ingestion_llm_unreachable" in rec.getMessage() for rec in caplog.records)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [500, 502, 503])
async def test_5xx_logs_unreachable(status, caplog):
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

        with caplog.at_level("WARNING"):
            await check_ingestion_llm()

    assert any("ingestion_llm_unreachable" in rec.getMessage() for rec in caplog.records)
    # Must NOT log config_error for 5xx.
    assert not any("ingestion_llm_config_error" in rec.getMessage() for rec in caplog.records)


@pytest.mark.asyncio
async def test_check_never_raises():
    """check_ingestion_llm() never raises — scheduler must always start."""
    from scheduler import check_ingestion_llm

    with patch("scheduler.httpx.AsyncClient", side_effect=Exception("anything")):
        # Must not raise.
        await check_ingestion_llm()
