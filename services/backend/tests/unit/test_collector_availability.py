"""Individual failed publishers cannot be hidden by a healthy source group."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.collector_availability import availability_report


def _snapshot() -> dict[str, str]:
    return {
        "_registry": json.dumps([
            {"id": "rss:A", "collector": "rss", "name": "A", "max_age_s": 3600},
            {"id": "rss:B", "collector": "rss", "name": "B", "max_age_s": 3600},
            {"id": "rss:C", "collector": "rss", "name": "C", "max_age_s": 3600},
        ]),
        "rss:A": json.dumps({"status": "available", "attempt_at": 100, "item_count": 0}),
        "rss:A:last_success": "100",
        "rss:B": json.dumps({"status": "unavailable", "attempt_at": 100,
                             "error_code": "http_403"}),
        "rss:B:last_success": "50",
    }


def test_healthy_peer_and_empty_feed_do_not_hide_failure_or_unknown() -> None:
    result = availability_report(_snapshot(), now=200)
    assert result.status == "degraded"
    assert [feed.status for feed in result.feeds] == ["available", "unavailable", "unknown"]
    assert result.feeds[0].item_count == 0
    assert result.feeds[1].last_success_at == 50
    assert result.feeds[1].error_code == "http_403"


def test_old_success_becomes_stale_without_inventing_a_new_fetch() -> None:
    result = availability_report(_snapshot(), now=5000)
    assert result.feeds[0].status == "stale"
    assert result.feeds[0].last_attempt_at == 100


@pytest.mark.parametrize("snapshot", [{}, {"_registry": "invalid"}, {"_registry": "[]"}])
def test_missing_or_corrupt_registry_is_not_empty_green(snapshot: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        availability_report(snapshot, now=200)


def test_corrupt_feed_is_unknown_and_does_not_hide_healthy_peers() -> None:
    snapshot = _snapshot()
    snapshot["rss:B"] = "invalid"
    result = availability_report(snapshot, now=200)
    assert [feed.status for feed in result.feeds] == ["available", "unknown", "unknown"]


def test_route_distinguishes_unavailable_telemetry_and_degraded_feeds() -> None:
    redis = AsyncMock()
    redis.__aenter__.return_value = redis
    redis.hgetall.return_value = _snapshot()
    with (
        patch("app.routers.feed_health.redis.from_url", return_value=redis),
        patch("app.routers.feed_health.time.time", return_value=200),
    ):
        response = TestClient(app).get("/api/health/collectors")
        assert response.status_code == 200
        assert response.json()["feeds"][1]["status"] == "unavailable"
        redis.hgetall.side_effect = ConnectionError("private redis address")
        response = TestClient(app).get("/api/health/collectors")
        assert response.status_code == 503
        assert "private" not in response.text
