from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.spatial import ScopeKind, SpatialScopeTokenV1
from app.models.timeline import ChronikExactSpatialActivationV1
from app.services.spatial_catalog import SpatialCatalogLoader
from app.services.spatial_filters import (
    GeoExtent,
    LongitudeSpan,
    ResolvedSpatialConstraint,
    compile_exact_event_query_plan,
    compile_extent_filter,
)

W = "?t_start=2026-06-01T00:00:00Z&t_end=2026-06-01T04:00:00Z&buckets=4"


@pytest.fixture
def client():
    return TestClient(app)


def _catalog_filter():
    derivation = "spatial-derive-v1-0123456789ab"
    token = SpatialScopeTokenV1(
        scope_key="country:UKR",
        kind=ScopeKind.COUNTRY,
        catalog_revision="spatial-v1-0123456789ab",
        derivation_revision=derivation,
        boundary_policy="odin-reference-v1",
        compatible_derivation_revisions=(derivation,),
    )
    extent = GeoExtent(
        kind="segments",
        south=40,
        north=53,
        longitude=(LongitudeSpan(20, 41),),
    )
    return compile_extent_filter(
        extent,
        constraint=ResolvedSpatialConstraint(
            token=token,
            extent=extent,
            country_scope_key="country:UKR",
            admin1_scope_key=None,
            admin2_scope_key=None,
        ),
    )


def _activation() -> ChronikExactSpatialActivationV1:
    return ChronikExactSpatialActivationV1(
        lane="event_occurrence",
        scope_kind="country",
        catalog_revision="spatial-v1-0123456789ab",
        derivation_revision="spatial-derive-v1-0123456789ab",
        coverage_revision="coverage-fixture-a",
        enabled=True,
        coverage_complete=True,
        index_plan_verified=True,
        stale_revision_ratio=0.0,
    )


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
        mock.side_effect = [rows, [], [], []]  # histogram, notable, incident, geo
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


def test_global_histogram_reuses_distinct_rows_without_an_accounting_scan(client):
    rows = _rows(
        ("2026-06-01T00:30:00Z", "civil.demo", "low"),
        ("2026-06-01T01:30:00Z", "civil.demo", "low"),
    )
    with patch("app.routers.timeline.read_query", new_callable=AsyncMock) as read:
        read.side_effect = [rows, [], [], []]  # histogram, notable, incident, geo
        response = client.get(f"/api/timeline/histogram{W}")

    assert response.status_code == 200
    assert response.json()["total_count"] == len(rows)
    assert len(read.await_args_list) == 4
    assert all("excluded_unlocated_count" not in call.args[0] for call in read.await_args_list)


def test_histogram_reversed_window_422(client):
    resp = client.get(
        "/api/timeline/histogram?t_start=2026-06-02T00:00:00Z&t_end=2026-06-01T00:00:00Z"
    )
    assert resp.status_code == 422


def test_histogram_buckets_over_cap_422(client):
    resp = client.get(f"/api/timeline/histogram{W}&buckets=999")
    assert resp.status_code == 422


def test_histogram_scope_key_and_bbox_are_rejected_before_query(client):
    with patch("app.routers.timeline.read_query", new_callable=AsyncMock) as mock:
        resp = client.get(
            f"/api/timeline/histogram{W}&scope_key=country:UKR"
            "&catalog_revision=spatial-v1-0123456789ab&bbox=20,40,41,53"
        )

    assert resp.status_code == 422
    mock.assert_not_awaited()


def test_scoped_histogram_uses_catalog_bbox_and_echoes_partial_accounting(client):
    loader = SpatialCatalogLoader(Path("/catalog-not-read-by-this-router-test"))
    app.state.spatial_catalog = loader
    with (
        patch(
            "app.routers.timeline.resolve_catalog_filter",
            new_callable=AsyncMock,
            return_value=_catalog_filter(),
        ) as resolve,
        patch("app.routers.timeline.read_query", new_callable=AsyncMock) as read,
    ):
        read.side_effect = [
            _rows(
                ("2026-06-01T00:30:00Z", "civil.demo", "low"),
                ("2026-06-01T01:30:00Z", "civil.demo", "low"),
                ("2026-06-01T02:30:00Z", "civil.demo", "low"),
            ),
            [{"excluded_unlocated_count": 2}],
            [],
            [],
            [],
        ]
        response = client.get(
            f"/api/timeline/histogram{W}&scope_key=country:UKR"
            "&catalog_revision=spatial-v1-0123456789ab"
        )

    assert response.status_code == 200
    application = response.json()["spatial_application"]
    assert application["requested_scope_key"] == "country:UKR"
    assert application["relation"] == "occurs-in"
    assert application["mode"] == "bbox_approximate"
    assert application["completeness"] == "partial"
    assert application["included_count"] == 3
    assert application["excluded_unlocated_count"] == 2
    accounting_query = read.await_args_list[1].args[0]
    assert "excluded_unlocated_count" in accounting_query
    assert " AS total" not in accounting_query
    resolve.assert_awaited_once_with(
        loader,
        "country:UKR",
        "spatial-v1-0123456789ab",
    )
    for call in read.await_args_list:
        query, parameters = call.args
        assert "country:UKR" not in query
        assert parameters["west"] == 20
        assert parameters["east"] == 41


def test_exact_histogram_reuses_static_event_rows_and_shared_accounting(client):
    loader = SpatialCatalogLoader(Path("/catalog-not-read-by-this-router-test"))
    app.state.spatial_catalog = loader
    compiled = _catalog_filter()
    exact = compile_exact_event_query_plan(
        compiled,
        coverage_revision="coverage-fixture-a",
        coverage_complete=True,
    )
    histogram_rows = [{
        "time": "2026-06-01T00:30:00Z",
        "codebook_type": "military.airstrike",
        "severity": "high",
    }]
    notable_rows = [{
        "id": "event-1",
        "time": "2026-06-01T00:30:00Z",
        "time_basis": "indexed",
        "title": "Reviewed event",
        "codebook_type": "military.airstrike",
        "severity": "high",
        "lat": 50.0,
        "lon": 30.0,
    }]
    incident_rows = [{
        "id": "incident-1",
        "time": "2026-06-01T00:45:00Z",
        "time_basis": "occurred",
        "title": "Reviewed incident",
        "severity": "critical",
        "lat": 50.1,
        "lon": 30.1,
    }]
    geo_rows = [{
        "id": "event-1",
        "time": "2026-06-01T00:30:00Z",
        "codebook_type": "military.airstrike",
        "severity": "high",
        "lat": 50.0,
        "lon": 30.0,
    }]
    with (
        patch(
            "app.routers.timeline.resolve_catalog_filter",
            new_callable=AsyncMock,
            return_value=compiled,
        ),
        patch(
            "app.routers.timeline._select_event_spatial_query",
            return_value=exact,
        ),
        patch("app.routers.timeline.read_queries", new_callable=AsyncMock) as read_many,
    ):
        read_many.return_value = [
            histogram_rows,
            notable_rows,
            incident_rows,
            geo_rows,
            [{
                "candidate_count": 4,
                "included_count": 1,
                "excluded_conflict_count": 1,
                "excluded_stale_revision_count": 1,
                "excluded_unsupported_count": 1,
            }],
        ]
        response = client.get(
            f"/api/timeline/histogram{W}&scope_key=country:UKR"
            "&catalog_revision=spatial-v1-0123456789ab"
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total_count"] == 1
    assert body["notables"][0]["id"] == "incident-1"
    assert body["notables"][0]["is_incident"] is True
    assert body["geo_located_count"] == 1
    assert body["geo_events"][0]["id"] == "event-1"
    assert body["spatial_application"]["mode"] == "semantic_key"
    assert body["spatial_application"]["included_count"] == 1
    assert body["spatial_application"]["excluded_unlocated_count"] == 0
    assert body["spatial_application"]["excluded_conflict_count"] == 1
    assert body["spatial_application"]["excluded_stale_revision_count"] == 1
    assert body["spatial_application"]["excluded_unsupported_count"] == 1
    read_many.assert_awaited_once()
    query_specs = read_many.await_args.args[0]
    assert len(query_specs) == 5
    histogram_query, histogram_parameters = query_specs[0]
    notable_query, notable_parameters = query_specs[1]
    incident_query, incident_parameters = query_specs[2]
    geo_query, geo_parameters = query_specs[3]
    accounting_query, accounting_parameters = query_specs[4]
    assert "l.country_scope_key = $scope_key" in histogram_query
    assert "LIMIT $limit" not in histogram_query
    assert "LIMIT 400" in notable_query
    assert "(i:Incident)" in incident_query
    assert "l.lat IS NOT NULL AND l.lon IS NOT NULL" in geo_query
    assert "excluded_conflict_count" in accounting_query
    assert all(
        parameters == histogram_parameters
        for parameters in (
            histogram_parameters,
            notable_parameters,
            incident_parameters,
            geo_parameters,
            accounting_parameters,
        )
    )


def test_active_exact_histogram_failure_never_retries_bbox(client):
    loader = SpatialCatalogLoader(Path("/catalog-not-read-by-this-router-test"))
    app.state.spatial_catalog = loader
    compiled = _catalog_filter()
    deployment_settings = SimpleNamespace(
        chronik_exact_spatial_activations=(_activation(),),
        chronik_exact_max_stale_revision_ratio=0.01,
    )
    with (
        patch(
            "app.routers.timeline.resolve_catalog_filter",
            new_callable=AsyncMock,
            return_value=compiled,
        ),
        patch("app.routers.timeline.settings", deployment_settings),
        patch("app.routers.timeline.read_queries", new_callable=AsyncMock) as read_many,
    ):
        read_many.side_effect = RuntimeError("exact histogram unavailable")
        response = client.get(
            f"/api/timeline/histogram{W}&scope_key=country:UKR"
            "&catalog_revision=spatial-v1-0123456789ab"
        )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "SPATIAL_FILTER_UNAVAILABLE"
    read_many.assert_awaited_once()
    query_specs = read_many.await_args.args[0]
    assert all("l.country_scope_key = $scope_key" in query for query, _ in query_specs)
    assert all("$bbox_off" not in query for query, _ in query_specs)


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
        mock.side_effect = [[], events, incidents, []]
        resp = client.get(f"/api/timeline/histogram{W}")
    data = resp.json()
    notables = data["notables"]
    assert len(notables) <= 40                       # cap
    assert notables[0]["severity"] == "critical"     # critical > high
    assert notables[0]["is_incident"] is True
    assert all(notables[i]["rank"] <= notables[i + 1]["rank"] for i in range(len(notables) - 1))


def test_notables_pass_bbox_params_to_queries(client):
    with patch("app.routers.timeline.read_query", new_callable=AsyncMock) as mock:
        mock.side_effect = [[], [], [], [], []]
        client.get(f"/api/timeline/histogram{W}&bbox=170,-10,-170,10")
    ev_params = mock.call_args_list[2].args[1]
    inc_params = mock.call_args_list[3].args[1]
    for p in (ev_params, inc_params):
        assert p["bbox_off"] is False
        assert p["west"] == 170.0 and p["east"] == -170.0  # anti-meridian preserved


def test_geo_events_capped_ranked_and_truncated(client):
    geo = [{"id": f"g{i}", "time": "2026-06-01T01:00:00Z", "codebook_type": "military.x",
            "severity": "low", "lat": 1.0 + i, "lon": 2.0} for i in range(205)]
    geo[0]["severity"] = "critical"
    with patch("app.routers.timeline.read_query", new_callable=AsyncMock) as mock:
        mock.side_effect = [[], [], [], geo]
        resp = client.get(f"/api/timeline/histogram{W}")
    data = resp.json()
    assert len(data["geo_events"]) == 200          # cap
    assert data["geo_truncated"] is True
    assert data["geo_located_count"] == 205
    assert data["geo_events"][0]["severity"] == "critical"   # severity-ranked


def test_histogram_notable_events_failure_returns_503(client):
    # A failure after the primary histogram read must be 503, not an unhandled 500.
    with patch("app.routers.timeline.read_query", new_callable=AsyncMock) as mock:
        mock.side_effect = [[], RuntimeError("boom")]
        resp = client.get(f"/api/timeline/histogram{W}")
    assert resp.status_code == 503


def test_histogram_incidents_failure_returns_503(client):
    with patch("app.routers.timeline.read_query", new_callable=AsyncMock) as mock:
        mock.side_effect = [[], [], RuntimeError("boom")]
        resp = client.get(f"/api/timeline/histogram{W}")
    assert resp.status_code == 503


def test_histogram_geo_failure_returns_503(client):
    with patch("app.routers.timeline.read_query", new_callable=AsyncMock) as mock:
        mock.side_effect = [[], [], [], RuntimeError("boom")]
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
