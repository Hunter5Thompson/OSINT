"""Runtime model-catalog and `/health` contract tests."""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

import main
from model_readiness import ModelReadiness, ReadinessReason, check_model_readiness


def _catalog_transport(*model_ids: str) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://vllm.test/v1/models"
        return httpx.Response(200, json={"data": [{"id": value} for value in model_ids]})

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_base_and_munin_present_is_ready() -> None:
    result = await check_model_readiness(
        base_url="https://vllm.test/v1",
        base_model="qwen3.5",
        synthesis_model="munin",
        transport=_catalog_transport("qwen3.5", "munin"),
    )

    assert result == ModelReadiness(
        ready=True,
        reason=ReadinessReason.READY,
        required_models=("qwen3.5", "munin"),
        missing_models=(),
    )


@pytest.mark.asyncio
async def test_missing_munin_is_not_ready_without_base_fallback() -> None:
    result = await check_model_readiness(
        base_url="https://vllm.test/v1",
        base_model="qwen3.5",
        synthesis_model="munin",
        transport=_catalog_transport("qwen3.5"),
    )

    assert result.ready is False
    assert result.reason is ReadinessReason.MISSING_MODELS
    assert result.required_models == ("qwen3.5", "munin")
    assert result.missing_models == ("munin",)


@pytest.mark.asyncio
async def test_empty_synthesis_model_requires_only_base() -> None:
    result = await check_model_readiness(
        base_url="https://vllm.test/v1",
        base_model="qwen3.5",
        synthesis_model="",
        transport=_catalog_transport("qwen3.5"),
    )

    assert result.ready is True
    assert result.required_models == ("qwen3.5",)


@pytest.mark.asyncio
async def test_unreachable_catalog_is_structured_not_ready() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    result = await check_model_readiness(
        base_url="https://vllm.test/v1",
        base_model="qwen3.5",
        synthesis_model="munin",
        transport=httpx.MockTransport(handler),
    )

    assert result.ready is False
    assert result.reason is ReadinessReason.CATALOG_UNAVAILABLE
    assert result.missing_models == ()


@pytest.mark.asyncio
async def test_invalid_catalog_is_structured_not_ready() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(200, json={"data": "not-a-list"})
    )

    result = await check_model_readiness(
        base_url="https://vllm.test/v1",
        base_model="qwen3.5",
        synthesis_model="munin",
        transport=transport,
    )

    assert result.ready is False
    assert result.reason is ReadinessReason.INVALID_CATALOG
    assert result.missing_models == ()


@pytest.mark.asyncio
async def test_health_returns_503_when_configured_model_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = ModelReadiness(
        ready=False,
        reason=ReadinessReason.MISSING_MODELS,
        required_models=("qwen3.5", "munin"),
        missing_models=("munin",),
    )
    check = AsyncMock(return_value=result)
    monkeypatch.setattr(main, "check_model_readiness", check)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app),
        base_url="http://intelligence.test",
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "reason": "missing_models",
        "required_models": ["qwen3.5", "munin"],
        "missing_models": ["munin"],
    }


@pytest.mark.asyncio
async def test_health_returns_200_when_all_configured_models_are_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = ModelReadiness(
        ready=True,
        reason=ReadinessReason.READY,
        required_models=("qwen3.5", "munin"),
        missing_models=(),
    )
    monkeypatch.setattr(main, "check_model_readiness", AsyncMock(return_value=result))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app),
        base_url="http://intelligence.test",
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "reason": "ready",
        "required_models": ["qwen3.5", "munin"],
        "missing_models": [],
    }
