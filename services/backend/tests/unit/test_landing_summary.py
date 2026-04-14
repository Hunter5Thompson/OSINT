"""Tests for the /api/landing/summary endpoint + service aggregator."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.landing_summary import LandingSummaryService


def _count_result(n: int) -> SimpleNamespace:
    """Mimic qdrant_client.models.CountResult (has `.count` attribute)."""
    return SimpleNamespace(count=n)


def _mock_qdrant(hotspots: int | Exception, nuntii: int | Exception) -> AsyncMock:
    mock = AsyncMock()

    async def _count(collection_name: str, count_filter=None, exact: bool = True):
        # Distinguish FIRMS filter by looking at conditions
        must = getattr(count_filter, "must", None) or []
        has_firms = any(
            getattr(getattr(c, "match", None), "value", None) == "firms" for c in must
        )
        val = hotspots if has_firms else nuntii
        if isinstance(val, Exception):
            raise val
        return _count_result(val)

    mock.count.side_effect = _count
    return mock


def _mock_read_query(conflict: int | Exception):
    async def _read_query(cypher: str, params: dict):
        if isinstance(conflict, Exception):
            raise conflict
        return [{"count": conflict}]

    return _read_query


@pytest.mark.asyncio
async def test_landing_summary_happy_path() -> None:
    """Mocked Qdrant + Neo4j return the expected counts."""
    qdrant = _mock_qdrant(hotspots=187, nuntii=28)

    with (
        patch(
            "app.services.landing_summary.get_qdrant_client",
            AsyncMock(return_value=qdrant),
        ),
        patch(
            "app.services.landing_summary.read_query",
            side_effect=_mock_read_query(44),
        ),
    ):
        client = TestClient(app)
        resp = client.get("/api/landing/summary?window=24h")

    assert resp.status_code == 200
    body = resp.json()
    assert body["window"] == "24h"
    assert body["hotspots_24h"] == 187
    assert body["hotspots_source"] == "qdrant:firms"
    assert body["conflict_24h"] == 44
    assert body["conflict_source"] == "neo4j:ucdp"
    assert body["nuntii_24h"] == 28
    assert body["nuntii_source"] == "qdrant:signals"
    assert body["libri_24h"] == 0
    assert body["libri_source"] == "reports:stub"
    assert body["reports_not_available_yet"] is True
    assert body["generated_at"].endswith("Z") or "+" in body["generated_at"]


@pytest.mark.asyncio
async def test_landing_summary_libri_always_stub() -> None:
    qdrant = _mock_qdrant(hotspots=0, nuntii=0)
    with (
        patch(
            "app.services.landing_summary.get_qdrant_client",
            AsyncMock(return_value=qdrant),
        ),
        patch(
            "app.services.landing_summary.read_query",
            side_effect=_mock_read_query(0),
        ),
    ):
        client = TestClient(app)
        resp = client.get("/api/landing/summary?window=24h")

    assert resp.status_code == 200
    body = resp.json()
    assert body["libri_24h"] == 0
    assert body["reports_not_available_yet"] is True


def test_landing_summary_invalid_window_returns_422() -> None:
    client = TestClient(app)
    resp = client.get("/api/landing/summary?window=72h")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_landing_summary_default_window_is_24h() -> None:
    qdrant = _mock_qdrant(hotspots=1, nuntii=2)
    with (
        patch(
            "app.services.landing_summary.get_qdrant_client",
            AsyncMock(return_value=qdrant),
        ),
        patch(
            "app.services.landing_summary.read_query",
            side_effect=_mock_read_query(3),
        ),
    ):
        client = TestClient(app)
        resp = client.get("/api/landing/summary")

    assert resp.status_code == 200
    assert resp.json()["window"] == "24h"


@pytest.mark.asyncio
async def test_landing_summary_qdrant_unavailable() -> None:
    """Qdrant raising → hotspots + nuntii null with :unavailable source markers."""
    qdrant = AsyncMock()
    qdrant.count.side_effect = RuntimeError("qdrant down")

    with (
        patch(
            "app.services.landing_summary.get_qdrant_client",
            AsyncMock(return_value=qdrant),
        ),
        patch(
            "app.services.landing_summary.read_query",
            side_effect=_mock_read_query(44),
        ),
    ):
        client = TestClient(app)
        resp = client.get("/api/landing/summary?window=24h")

    assert resp.status_code == 200
    body = resp.json()
    assert body["hotspots_24h"] is None
    assert body["hotspots_source"].endswith(":unavailable")
    assert body["nuntii_24h"] is None
    assert body["nuntii_source"].endswith(":unavailable")
    assert body["conflict_24h"] == 44
    assert body["conflict_source"] == "neo4j:ucdp"


@pytest.mark.asyncio
async def test_landing_summary_neo4j_unavailable() -> None:
    qdrant = _mock_qdrant(hotspots=5, nuntii=6)

    with (
        patch(
            "app.services.landing_summary.get_qdrant_client",
            AsyncMock(return_value=qdrant),
        ),
        patch(
            "app.services.landing_summary.read_query",
            side_effect=_mock_read_query(RuntimeError("neo4j down")),
        ),
    ):
        client = TestClient(app)
        resp = client.get("/api/landing/summary?window=24h")

    assert resp.status_code == 200
    body = resp.json()
    assert body["conflict_24h"] is None
    assert body["conflict_source"].endswith(":unavailable")
    assert body["hotspots_24h"] == 5
    assert body["nuntii_24h"] == 6


@pytest.mark.asyncio
async def test_landing_summary_all_sources_unavailable() -> None:
    qdrant = AsyncMock()
    qdrant.count.side_effect = RuntimeError("boom")

    with (
        patch(
            "app.services.landing_summary.get_qdrant_client",
            AsyncMock(return_value=qdrant),
        ),
        patch(
            "app.services.landing_summary.read_query",
            side_effect=_mock_read_query(RuntimeError("boom")),
        ),
    ):
        client = TestClient(app)
        resp = client.get("/api/landing/summary?window=24h")

    assert resp.status_code == 200
    body = resp.json()
    assert body["hotspots_24h"] is None
    assert body["conflict_24h"] is None
    assert body["nuntii_24h"] is None
    assert body["hotspots_source"].endswith(":unavailable")
    assert body["conflict_source"].endswith(":unavailable")
    assert body["nuntii_source"].endswith(":unavailable")
    assert body["libri_24h"] == 0
    assert body["libri_source"] == "reports:stub"
    assert body["reports_not_available_yet"] is True


@pytest.mark.asyncio
async def test_service_layer_direct_call() -> None:
    """Unit-test the service without the HTTP layer."""
    qdrant = _mock_qdrant(hotspots=10, nuntii=20)

    with (
        patch(
            "app.services.landing_summary.get_qdrant_client",
            AsyncMock(return_value=qdrant),
        ),
        patch(
            "app.services.landing_summary.read_query",
            side_effect=_mock_read_query(30),
        ),
    ):
        service = LandingSummaryService()
        summary = await service.get_summary(window=timedelta(hours=24))

    assert summary.window == "24h"
    assert summary.hotspots_24h == 10
    assert summary.hotspots_source == "qdrant:firms"
    assert summary.conflict_24h == 30
    assert summary.conflict_source == "neo4j:ucdp"
    assert summary.nuntii_24h == 20
    assert summary.nuntii_source == "qdrant:signals"
    assert summary.libri_24h == 0
    assert summary.libri_source == "reports:stub"
    assert summary.reports_not_available_yet is True
