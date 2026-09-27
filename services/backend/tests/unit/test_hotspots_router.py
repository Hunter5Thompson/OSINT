"""Hotspot cache rows that cannot be placed must not blank or 500 the list."""

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.main import app


def _cache(payload: object) -> AsyncMock:
    cache = AsyncMock()
    cache.get.return_value = payload
    app.state.cache = cache
    return cache


def test_empty_cache_uses_builtin_hotspots() -> None:
    _cache([])

    body = TestClient(app).get("/api/hotspots").json()

    assert any(item["id"] == "ukr-001" for item in body)


def test_bad_row_is_skipped_and_low_is_moderate() -> None:
    _cache(
        [
            {
                "id": "bad",
                "name": "Bad",
                "latitude": "48,3",
                "longitude": 10,
                "threat_level": "HIGH",
            },
            {
                "id": "good",
                "name": "Good",
                "lat": 48.1,
                "lon": 11.5,
                "region": "Europe",
                "threat_level": "LOW",
                "description": "watch",
                "sources": "Reuters",
            },
            {
                "id": "island",
                "name": "Missing",
                "threat_level": "HIGH",
            },
        ]
    )

    response = TestClient(app).get("/api/hotspots")

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body] == ["good"]
    assert body[0]["threat_level"] == "MODERATE"
    assert body[0]["sources"] == ["Reuters"]
    assert body[0]["latitude"] == 48.1


def test_non_list_cache_falls_through_to_defaults() -> None:
    _cache({"id": "not-a-list"})

    body = TestClient(app).get("/api/hotspots").json()

    assert any(item["id"] == "ukr-001" for item in body)
