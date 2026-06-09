from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

W = "?t_start=2026-06-01T00:00:00Z&t_end=2026-06-01T04:00:00Z&buckets=4"


@pytest.fixture
def client():
    return TestClient(app)


def _rows(*triples):
    # triples: (iso_time, codebook_type, severity)
    return [{"time": t, "codebook_type": c, "severity": s} for t, c, s in triples]


def test_histogram_bins_and_dominant_category_is_modal(client):
    rows = _rows(
        *[("2026-06-01T00:30:00Z", "civil.demonstration", "low")] * 200,
        ("2026-06-01T00:45:00Z", "military.airstrike", "critical"),  # outlier
        ("2026-06-01T02:30:00Z", "conflict.armed", None),
    )
    with patch("app.routers.timeline.read_query", new_callable=AsyncMock) as mock:
        mock.side_effect = [rows, [], [], []]  # hist, notable-events, incidents, geo
        resp = client.get(f"/api/timeline/histogram{W}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["bucket_ms"] == 3_600_000  # 4h / 4
    b0 = next(b for b in data["buckets"] if b["count"] == 201)
    assert b0["dominant_category"] == "civil"          # 200 civil beats 1 military
    assert b0["by_category"]["military"] == 1
    assert b0["by_severity"]["critical"] == 1 and b0["by_severity"]["low"] == 200
    # GDELT-style null severity -> 'unknown' bucket, never random
    b2 = next(b for b in data["buckets"] if b["count"] == 1)
    assert b2["by_severity"].get("unknown") == 1
    assert data["total_count"] == 202


def test_histogram_reversed_window_422(client):
    resp = client.get(
        "/api/timeline/histogram?t_start=2026-06-02T00:00:00Z&t_end=2026-06-01T00:00:00Z"
    )
    assert resp.status_code == 422


def test_histogram_buckets_over_cap_422(client):
    resp = client.get(f"/api/timeline/histogram{W}&buckets=999")
    assert resp.status_code == 422


def test_histogram_neo4j_down_503(client):
    with patch("app.routers.timeline.read_query", new_callable=AsyncMock) as mock:
        mock.side_effect = RuntimeError("boom")
        resp = client.get(f"/api/timeline/histogram{W}")
    assert resp.status_code == 503
