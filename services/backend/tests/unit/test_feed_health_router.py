"""A corrupt freshness cache is recomputed instead of failing the health route."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.services.feed_freshness import FeedFreshnessReport


def _report() -> FeedFreshnessReport:
    return FeedFreshnessReport(status="ok", checked_at=datetime.now(UTC), sources=[])


def test_invalid_cache_recomputes() -> None:
    cache = AsyncMock()
    cache.get.return_value = {"status": "broken"}
    app.state.cache = cache
    report = _report()

    with (
        patch("app.routers.feed_health.get_qdrant_client", AsyncMock(return_value=object())),
        patch(
            "app.routers.feed_health.compute_feed_freshness",
            AsyncMock(return_value=report),
        ) as compute,
    ):
        response = TestClient(app).get("/api/health/feeds")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    compute.assert_awaited()


def test_valid_cache_skips_qdrant() -> None:
    cache = AsyncMock()
    cache.get.return_value = _report().model_dump(mode="json")
    app.state.cache = cache

    with patch(
        "app.routers.feed_health.compute_feed_freshness",
        AsyncMock(side_effect=AssertionError("recomputed")),
    ):
        response = TestClient(app).get("/api/health/feeds")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
