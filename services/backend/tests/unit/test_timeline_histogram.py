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


def test_notables_union_capped_and_ranked(client):
    events = [{"id": f"ev{i}", "time": "2026-06-01T01:00:00Z", "time_basis": "indexed",
               "severity": "high", "title": "T", "codebook_type": "conflict.armed",
               "lat": None, "lon": None} for i in range(50)]
    incidents = [{"id": "inc-1", "time": "2026-06-01T02:00:00Z", "time_basis": "occurred",
                  "severity": "critical", "title": "Strike", "lat": 50.0, "lon": 30.0}]
    with patch("app.routers.timeline.read_query", new_callable=AsyncMock) as mock:
        mock.side_effect = [[], events, incidents, []]  # hist, notable-events, incidents, geo
        resp = client.get(f"/api/timeline/histogram{W}")
    data = resp.json()
    notables = data["notables"]
    assert len(notables) <= 40                       # cap
    assert notables[0]["severity"] == "critical"     # critical > high
    assert notables[0]["is_incident"] is True
    assert all(notables[i]["rank"] <= notables[i + 1]["rank"] for i in range(len(notables) - 1))


def test_notables_pass_bbox_params_to_queries(client):
    with patch("app.routers.timeline.read_query", new_callable=AsyncMock) as mock:
        mock.side_effect = [[], [], [], []]  # hist, notable-events, incidents, geo
        client.get(f"/api/timeline/histogram{W}&bbox=170,-10,-170,10")
    ev_params = mock.call_args_list[1].args[1]
    inc_params = mock.call_args_list[2].args[1]
    for p in (ev_params, inc_params):
        assert p["bbox_off"] is False
        assert p["west"] == 170.0 and p["east"] == -170.0  # anti-meridian preserved


def test_geo_events_capped_ranked_and_truncated(client):
    geo = [{"id": f"g{i}", "time": "2026-06-01T01:00:00Z", "codebook_type": "military.x",
            "severity": "low", "lat": 1.0 + i, "lon": 2.0} for i in range(205)]
    geo[0]["severity"] = "critical"
    with patch("app.routers.timeline.read_query", new_callable=AsyncMock) as mock:
        mock.side_effect = [[], [], [], geo]  # hist, notable-events, incidents, geo
        resp = client.get(f"/api/timeline/histogram{W}")
    data = resp.json()
    assert len(data["geo_events"]) == 200          # cap
    assert data["geo_truncated"] is True
    assert data["geo_located_count"] == 205
    assert data["geo_events"][0]["severity"] == "critical"   # severity-ranked


def test_histogram_notable_events_failure_returns_503(client):
    # finding #1: a failure in the SECOND read_query (notable-events) must be 503, not 500
    with patch("app.routers.timeline.read_query", new_callable=AsyncMock) as mock:
        mock.side_effect = [[], RuntimeError("boom")]  # hist ok, notable-events raises
        resp = client.get(f"/api/timeline/histogram{W}")
    assert resp.status_code == 503


def test_histogram_incidents_failure_returns_503(client):
    with patch("app.routers.timeline.read_query", new_callable=AsyncMock) as mock:
        mock.side_effect = [[], [], RuntimeError("boom")]  # incidents (3rd read) raises
        resp = client.get(f"/api/timeline/histogram{W}")
    assert resp.status_code == 503


def test_histogram_geo_failure_returns_503(client):
    with patch("app.routers.timeline.read_query", new_callable=AsyncMock) as mock:
        mock.side_effect = [[], [], [], RuntimeError("boom")]  # geo (4th) raises
        resp = client.get(f"/api/timeline/histogram{W}")
    assert resp.status_code == 503


def test_notable_events_query_prefilters_high_critical_in_cypher():
    # finding #3: high/critical synonyms must be filtered IN Cypher so the LIMIT can't be
    # starved by low/medium rows before Python ranks.
    from app.routers.timeline import _NOTABLE_EVENTS_QUERY

    q = _NOTABLE_EVENTS_QUERY.lower()
    assert "tolower" in q
    for syn in ("high", "elevated", "critical", "severe", "extreme"):
        assert f"'{syn}'" in q


def test_notable_incidents_query_returns_incident_node_id():
    from app.routers.timeline import _NOTABLE_INCIDENTS_QUERY

    q = _NOTABLE_INCIDENTS_QUERY.lower()
    assert "i.id as id" in q
    assert "i.incident_id as id" not in q
