from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.spatial import (
    CatalogProblemCode,
    ScopeKind,
    SpatialCatalogProblem,
    SpatialScopeTokenV1,
)
from app.models.timeline import ChronikExactSpatialActivationV1
from app.services.spatial_catalog import SpatialCatalogLoader
from app.services.spatial_filters import (
    GeoExtent,
    LongitudeSpan,
    ResolvedSpatialConstraint,
    compile_exact_event_query_plan,
    compile_extent_filter,
)

W = "?t_start=2026-05-01T00:00:00Z&t_end=2026-05-02T00:00:00Z"


@pytest.fixture
def client():
    return TestClient(app)


def _catalog_filter(
    *,
    scope_key: str = "country:UKR",
    catalog_revision: str = "spatial-v1-0123456789ab",
    derivation_revision: str = "spatial-derive-v1-0123456789ab",
    kind: ScopeKind = ScopeKind.COUNTRY,
    extent: GeoExtent | None = None,
):
    token = SpatialScopeTokenV1(
        scope_key=scope_key,
        kind=kind,
        catalog_revision=catalog_revision,
        derivation_revision=derivation_revision,
        boundary_policy="odin-reference-v1",
        compatible_derivation_revisions=(derivation_revision,),
    )
    selected_extent = extent or GeoExtent(
        kind="segments",
        south=40,
        north=53,
        longitude=(LongitudeSpan(20, 41),),
    )
    constraint = ResolvedSpatialConstraint(
        token=token,
        extent=selected_extent,
        country_scope_key=scope_key if kind is ScopeKind.COUNTRY else None,
        admin1_scope_key=None,
        admin2_scope_key=None,
    )
    return compile_extent_filter(selected_extent, constraint=constraint)


def _exact_activation(**overrides: object) -> ChronikExactSpatialActivationV1:
    return ChronikExactSpatialActivationV1.model_validate({
        "lane": "event_occurrence",
        "scope_kind": "country",
        "catalog_revision": "spatial-v1-0123456789ab",
        "derivation_revision": "spatial-derive-v1-0123456789ab",
        "coverage_revision": "coverage-fixture-a",
        "enabled": True,
        "coverage_complete": True,
        "index_plan_verified": True,
        "stale_revision_ratio": 0.0,
        **overrides,
    })


@pytest.fixture
def spatial_loader():
    loader = SpatialCatalogLoader(Path("/catalog-not-read-by-this-router-test"))
    app.state.spatial_catalog = loader
    return loader


def test_events_window_returns_samples(client):
    with patch("app.routers.timeline.read_query", new_callable=AsyncMock) as mock:
        mock.side_effect = [
            [{
                "id": "gdelt:event:1", "title": None, "codebook_type": "military.airstrike",
                "severity": None, "time": "2026-05-01T06:00:00Z", "time_basis": "indexed",
                "location_name": None, "country": None, "lat": None, "lon": None,
            }],
            [{"total": 1}],
        ]
        resp = client.get(f"/api/timeline/window{W}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["domain"] == "events" and data["tier"] == "coarse"
    assert data["samples"][0]["kind"] == "event"
    assert data["samples"][0]["title"] is None  # GDELT nullable
    assert data["samples"][0]["time_basis"] == "indexed"
    assert data["total_count"] == 1 and data["truncated"] is False
    assert data["spatial_application"] == {
        "schema_version": 1,
        "requested_scope_key": None,
        "catalog_revision": None,
        "derivation_revision": None,
        "boundary_policy": None,
        "relation": "occurs-in",
        "mode": "global",
        "completeness": "complete",
        "included_count": 1,
        "excluded_unlocated_count": 0,
        "excluded_outside_count": 0,
        "excluded_conflict_count": 0,
        "excluded_stale_revision_count": 0,
        "excluded_unsupported_count": 0,
    }


def test_reversed_window_422(client):
    resp = client.get(
        "/api/timeline/window?t_start=2026-05-02T00:00:00Z&t_end=2026-05-01T00:00:00Z"
    )
    assert resp.status_code == 422


def test_limit_over_cap_422(client):
    resp = client.get(f"/api/timeline/window{W}&limit=999")
    assert resp.status_code == 422


def test_events_with_movement_kind_422(client):
    resp = client.get(f"/api/timeline/window{W}&movement_kind=mil_aircraft")
    assert resp.status_code == 422


def test_events_fine_422(client):
    resp = client.get(f"/api/timeline/window{W}&tier=fine")
    assert resp.status_code == 422


def test_window_scope_key_and_bbox_are_rejected_before_query(client):
    with patch("app.routers.timeline.read_query", new_callable=AsyncMock) as mock:
        resp = client.get(
            f"/api/timeline/window{W}&scope_key=country:UKR"
            "&catalog_revision=spatial-v1-0123456789ab&bbox=20,40,41,53"
        )

    assert resp.status_code == 422
    mock.assert_not_awaited()


def test_window_invalid_catalog_revision_is_422_before_query(client):
    with patch("app.routers.timeline.read_query", new_callable=AsyncMock) as mock:
        resp = client.get(
            f"/api/timeline/window{W}&scope_key=world&catalog_revision=latest"
        )

    assert resp.status_code == 422
    mock.assert_not_awaited()


def test_scoped_event_window_echoes_catalog_token_and_distinct_accounting(
    client,
    spatial_loader,
):
    compiled = _catalog_filter()
    with (
        patch(
            "app.routers.timeline.resolve_catalog_filter",
            new_callable=AsyncMock,
            return_value=compiled,
        ) as resolve,
        patch("app.routers.timeline.read_query", new_callable=AsyncMock) as read,
    ):
        read.side_effect = [
            [{
                "id": "gdelt:event:1",
                "time": "2026-05-01T06:00:00Z",
                "time_basis": "indexed",
            }],
            [{"total": 3, "excluded_unlocated_count": 0}],
        ]
        response = client.get(
            f"/api/timeline/window{W}&scope_key=country:UKR"
            "&catalog_revision=spatial-v1-0123456789ab&limit=1"
        )

    assert response.status_code == 200
    body = response.json()
    assert len(body["samples"]) == 1
    assert body["spatial_application"] == {
        "schema_version": 1,
        "requested_scope_key": "country:UKR",
        "catalog_revision": "spatial-v1-0123456789ab",
        "derivation_revision": "spatial-derive-v1-0123456789ab",
        "boundary_policy": "odin-reference-v1",
        "relation": "occurs-in",
        "mode": "bbox_approximate",
        "completeness": "partial",
        "included_count": 3,
        "excluded_unlocated_count": 0,
        "excluded_outside_count": 0,
        "excluded_conflict_count": 0,
        "excluded_stale_revision_count": 0,
        "excluded_unsupported_count": 0,
    }
    resolve.assert_awaited_once_with(
        spatial_loader,
        "country:UKR",
        "spatial-v1-0123456789ab",
    )
    for call in read.await_args_list:
        query, parameters = call.args
        assert "country:UKR" not in query
        assert parameters["west"] == 20
        assert parameters["east"] == 41
    count_query = read.await_args_list[1].args[0]
    assert count_query.count("MATCH (ev:Event)") == 1
    assert "0 AS excluded_unlocated_count" in count_query


def test_exact_event_window_uses_one_pinned_token_and_reports_mixed_coverage(
    client,
    spatial_loader,
):
    compiled = _catalog_filter()
    exact = compile_exact_event_query_plan(
        compiled,
        coverage_revision="coverage-fixture-a",
        coverage_complete=True,
    )
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
            [{
                "id": "gdelt:event:1",
                "time": "2026-05-01T06:00:00Z",
                "time_basis": "indexed",
            }],
            [{
                "candidate_count": 8,
                "included_count": 3,
                "excluded_conflict_count": 1,
                "excluded_stale_revision_count": 2,
                "excluded_unsupported_count": 2,
            }],
        ]
        response = client.get(
            f"/api/timeline/window{W}&scope_key=country:UKR"
            "&catalog_revision=spatial-v1-0123456789ab&limit=1"
        )

    assert response.status_code == 200
    body = response.json()
    assert body["bbox"] is None
    assert body["total_count"] == 3
    assert len(body["samples"]) == 1
    assert body["truncated"] is True
    assert body["spatial_application"] == {
        "schema_version": 1,
        "requested_scope_key": "country:UKR",
        "catalog_revision": "spatial-v1-0123456789ab",
        "derivation_revision": "spatial-derive-v1-0123456789ab",
        "boundary_policy": "odin-reference-v1",
        "relation": "occurs-in",
        "mode": "semantic_key",
        "completeness": "partial",
        "included_count": 3,
        "excluded_unlocated_count": 0,
        "excluded_outside_count": 0,
        "excluded_conflict_count": 1,
        "excluded_stale_revision_count": 2,
        "excluded_unsupported_count": 2,
    }
    query_specs = read_many.await_args.args[0]
    samples_query, samples_parameters = query_specs[0]
    count_query, count_parameters = query_specs[1]
    assert "l.country_scope_key = $scope_key" in samples_query
    assert "l.spatial_conflict = false" in samples_query
    assert "excluded_stale_revision_count" in count_query
    assert samples_parameters == count_parameters
    assert samples_parameters["scope_key"] == "country:UKR"
    assert samples_parameters["compatible_revisions"] == [
        "spatial-derive-v1-0123456789ab"
    ]
    assert {"bbox_off", "west", "east", "south", "north"}.isdisjoint(
        samples_parameters
    )


@pytest.mark.parametrize(
    ("coverage_complete", "expected_completeness"),
    [(False, "partial"), (True, "complete")],
)
def test_exact_complete_requires_lane_contract_and_zero_exclusions(
    client,
    spatial_loader,
    coverage_complete,
    expected_completeness,
):
    compiled = _catalog_filter()
    exact = compile_exact_event_query_plan(
        compiled,
        coverage_revision="coverage-fixture-a",
        coverage_complete=coverage_complete,
    )
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
            [],
            [{
                "candidate_count": 0,
                "included_count": 0,
                "excluded_conflict_count": 0,
                "excluded_stale_revision_count": 0,
                "excluded_unsupported_count": 0,
            }],
        ]
        response = client.get(
            f"/api/timeline/window{W}&scope_key=country:UKR"
            "&catalog_revision=spatial-v1-0123456789ab"
        )

    assert response.status_code == 200
    assert (
        response.json()["spatial_application"]["completeness"]
        == expected_completeness
    )


def test_server_activation_selects_exact_and_emits_revisioned_metric(
    client,
    spatial_loader,
):
    compiled = _catalog_filter()
    deployment_settings = SimpleNamespace(
        chronik_exact_spatial_activations=(_exact_activation(),),
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
        patch("app.routers.timeline.log") as logger,
    ):
        read_many.return_value = [
            [],
            [{
                "candidate_count": 0,
                "included_count": 0,
                "excluded_conflict_count": 0,
                "excluded_stale_revision_count": 0,
                "excluded_unsupported_count": 0,
            }],
        ]
        response = client.get(
            f"/api/timeline/window{W}&scope_key=country:UKR"
            "&catalog_revision=spatial-v1-0123456789ab"
        )

    assert response.status_code == 200
    assert response.json()["spatial_application"]["mode"] == "semantic_key"
    selected = next(
        call.kwargs
        for call in logger.info.call_args_list
        if call.args[0] == "spatial_exact_activation_selected"
    )
    assert selected == {
        "consumer": "chronik",
        "lane": "event_occurrence",
        "scope_key": "country:UKR",
        "scope_kind": "country",
        "catalog_revision": "spatial-v1-0123456789ab",
        "derivation_revision": "spatial-derive-v1-0123456789ab",
        "coverage_revision": "coverage-fixture-a",
    }


def test_new_derivation_revision_rejects_exact_and_stays_explicit_bbox(
    client,
    spatial_loader,
):
    compiled = _catalog_filter(
        derivation_revision="spatial-derive-v1-bbbbbbbbbbbb",
    )
    deployment_settings = SimpleNamespace(
        chronik_exact_spatial_activations=(_exact_activation(),),
        chronik_exact_max_stale_revision_ratio=0.01,
    )
    with (
        patch(
            "app.routers.timeline.resolve_catalog_filter",
            new_callable=AsyncMock,
            return_value=compiled,
        ),
        patch("app.routers.timeline.settings", deployment_settings),
        patch("app.routers.timeline.read_query", new_callable=AsyncMock) as read,
        patch("app.routers.timeline.log") as logger,
    ):
        read.side_effect = [[], [{"total": 0, "excluded_unlocated_count": 0}]]
        response = client.get(
            f"/api/timeline/window{W}&scope_key=country:UKR"
            "&catalog_revision=spatial-v1-0123456789ab"
        )

    assert response.status_code == 200
    assert response.json()["spatial_application"]["mode"] == "bbox_approximate"
    rejected = next(
        call.kwargs
        for call in logger.info.call_args_list
        if call.args[0] == "spatial_exact_activation_rejected"
    )
    assert rejected["cause"] == "derivation_revision_mismatch"
    assert rejected["coverage_revision"] is None
    assert "l.country_scope_key = $scope_key" not in read.await_args_list[0].args[0]


def test_client_cannot_enable_exact_when_server_registry_is_default_off(
    client,
    spatial_loader,
):
    compiled = _catalog_filter()
    deployment_settings = SimpleNamespace(
        chronik_exact_spatial_activations=(),
        chronik_exact_max_stale_revision_ratio=0.01,
    )
    with (
        patch(
            "app.routers.timeline.resolve_catalog_filter",
            new_callable=AsyncMock,
            return_value=compiled,
        ),
        patch("app.routers.timeline.settings", deployment_settings),
        patch("app.routers.timeline.read_query", new_callable=AsyncMock) as read,
    ):
        read.side_effect = [[], [{"total": 0, "excluded_unlocated_count": 0}]]
        response = client.get(
            f"/api/timeline/window{W}&scope_key=country:UKR"
            "&catalog_revision=spatial-v1-0123456789ab&exact=true"
        )

    assert response.status_code == 200
    assert response.json()["spatial_application"]["mode"] == "bbox_approximate"
    assert "l.country_scope_key = $scope_key" not in read.await_args_list[0].args[0]


def test_active_exact_failure_returns_spatial_filter_unavailable_without_bbox_retry(
    client,
    spatial_loader,
):
    compiled = _catalog_filter()
    deployment_settings = SimpleNamespace(
        chronik_exact_spatial_activations=(_exact_activation(),),
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
        read_many.side_effect = RuntimeError("exact count unavailable")
        response = client.get(
            f"/api/timeline/window{W}&scope_key=country:UKR"
            "&catalog_revision=spatial-v1-0123456789ab"
        )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "SPATIAL_FILTER_UNAVAILABLE"
    assert response.headers["cache-control"] == "no-store"
    read_many.assert_awaited_once()
    query_specs = read_many.await_args.args[0]
    assert len(query_specs) == 2
    assert all(
        "l.country_scope_key = $scope_key" in query
        for query, _ in query_specs
    )
    assert all("$bbox_off" not in query for query, _ in query_specs)


def test_exact_accounting_violation_is_not_logged_as_a_neo4j_query_failure(
    client,
    spatial_loader,
):
    compiled = _catalog_filter()
    exact = compile_exact_event_query_plan(
        compiled,
        coverage_revision="coverage-fixture-a",
        coverage_complete=True,
    )
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
        patch(
            "app.routers.timeline.read_queries",
            new_callable=AsyncMock,
            return_value=[
                [{"id": "event-1", "time": "2026-05-01T06:00:00Z"}],
                [{
                    "candidate_count": 0,
                    "included_count": 0,
                    "excluded_conflict_count": 0,
                    "excluded_stale_revision_count": 0,
                    "excluded_unsupported_count": 0,
                }],
            ],
        ),
        patch("app.routers.timeline.log") as logger,
    ):
        response = client.get(
            f"/api/timeline/window{W}&scope_key=country:UKR"
            "&catalog_revision=spatial-v1-0123456789ab"
        )

    assert response.status_code == 503
    events = [call.args[0] for call in logger.error.call_args_list]
    assert events == ["timeline_exact_event_accounting_invalid"]


def test_new_client_world_token_echoes_identity_while_using_global_query(
    client,
    spatial_loader,
):
    compiled = _catalog_filter(
        scope_key="world",
        kind=ScopeKind.WORLD,
        extent=GeoExtent(kind="world"),
    )
    with (
        patch(
            "app.routers.timeline.resolve_catalog_filter",
            new_callable=AsyncMock,
            return_value=compiled,
        ),
        patch("app.routers.timeline.read_query", new_callable=AsyncMock) as read,
    ):
        read.side_effect = [[], [{"total": 0, "excluded_unlocated_count": 4}]]
        response = client.get(
            f"/api/timeline/window{W}&scope_key=world"
            "&catalog_revision=spatial-v1-0123456789ab"
        )

    application = response.json()["spatial_application"]
    assert application["requested_scope_key"] == "world"
    assert application["catalog_revision"] == "spatial-v1-0123456789ab"
    assert application["mode"] == "global"
    assert application["completeness"] == "complete"
    assert application["excluded_unlocated_count"] == 0


def test_requested_scope_key_echoes_the_literal_reviewed_alias(client, spatial_loader):
    compiled = _catalog_filter()
    with (
        patch(
            "app.routers.timeline.resolve_catalog_filter",
            new_callable=AsyncMock,
            return_value=compiled,
        ) as resolve,
        patch("app.routers.timeline.read_query", new_callable=AsyncMock) as read,
    ):
        read.side_effect = [[], [{"total": 0, "excluded_unlocated_count": 0}]]
        response = client.get(
            f"/api/timeline/window{W}&scope_key=country:ukr"
            "&catalog_revision=spatial-v1-0123456789ab"
        )

    assert response.status_code == 200
    assert response.json()["spatial_application"]["requested_scope_key"] == "country:ukr"
    resolve.assert_awaited_once_with(
        spatial_loader,
        "country:ukr",
        "spatial-v1-0123456789ab",
    )


def test_catalog_resolution_failure_never_falls_back_to_global_query(
    client,
    spatial_loader,
):
    problem = SpatialCatalogProblem(
        code=CatalogProblemCode.CATALOG_UNAVAILABLE,
        message="Spatial catalog is unavailable",
        recoverable=True,
    )
    with (
        patch(
            "app.routers.timeline.resolve_catalog_filter",
            new_callable=AsyncMock,
            return_value=problem,
        ),
        patch("app.routers.timeline.read_query", new_callable=AsyncMock) as read,
        patch("app.routers.timeline.log") as logger,
    ):
        response = client.get(
            f"/api/timeline/window{W}&scope_key=country:UKR"
            "&catalog_revision=spatial-v1-0123456789ab"
        )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "CATALOG_UNAVAILABLE"
    read.assert_not_awaited()
    rejected = next(
        call for call in logger.info.call_args_list
        if call.args[0] == "spatial_filter_unsupported"
    )
    assert rejected.kwargs["scope_kind"] == "country"
    assert rejected.kwargs["catalog_revision"] == "spatial-v1-0123456789ab"
    assert rejected.kwargs["cause"] == "CATALOG_UNAVAILABLE"
    assert rejected.kwargs["duration_ms"] >= 0


def test_scoped_filter_logs_request_mode_coverage_and_latency_without_query_content(
    client,
    spatial_loader,
):
    compiled = _catalog_filter()
    with (
        patch(
            "app.routers.timeline.resolve_catalog_filter",
            new_callable=AsyncMock,
            return_value=compiled,
        ),
        patch("app.routers.timeline.read_query", new_callable=AsyncMock) as read,
        patch("app.routers.timeline.log") as logger,
    ):
        read.side_effect = [[], [{"total": 3, "excluded_unlocated_count": 2}]]
        response = client.get(
            f"/api/timeline/window{W}&scope_key=country:UKR"
            "&catalog_revision=spatial-v1-0123456789ab"
        )

    assert response.status_code == 200
    requested = next(
        call.kwargs for call in logger.debug.call_args_list
        if call.args[0] == "spatial_filter_requested"
    )
    assert requested == {
        "consumer": "chronik",
        "scope_key": "country:UKR",
        "scope_kind": "country",
        "catalog_revision": "spatial-v1-0123456789ab",
    }
    events = {call.args[0]: call.kwargs for call in logger.info.call_args_list}
    applied = events["spatial_filter_applied"]
    assert applied["scope_kind"] == "country"
    assert applied["filter_mode"] == "bbox_approximate"
    assert applied["completeness"] == "partial"
    assert applied["included_count"] == 3
    assert applied["excluded_unlocated_count"] == 2
    assert applied["duration_ms"] >= 0
    assert {"t_start", "t_end", "bbox", "query"}.isdisjoint(applied)


def test_scoped_movement_uses_intersects_relation(client, spatial_loader):
    compiled = _catalog_filter()
    with (
        patch(
            "app.routers.timeline.resolve_catalog_filter",
            new_callable=AsyncMock,
            return_value=compiled,
        ),
        patch("app.routers.timeline.read_query", new_callable=AsyncMock) as read,
    ):
        read.side_effect = [[{
            "icao24": "abc123",
            "points": [{"ts_ms": 1, "lat": 50.0, "lon": 30.0}],
        }], [{
            "total": 1,
            "excluded_unlocated_count": 0,
            "excluded_outside_count": 2,
        }]]
        response = client.get(
            f"/api/timeline/window{W}&domain=movements&tier=fine"
            "&movement_kind=mil_aircraft&scope_key=country:UKR"
            "&catalog_revision=spatial-v1-0123456789ab"
        )

    application = response.json()["spatial_application"]
    assert application["relation"] == "intersects"
    assert application["mode"] == "bbox_approximate"
    assert application["excluded_unlocated_count"] == 0
    assert application["excluded_outside_count"] == 2
    samples_query, count_query = (call.args[0] for call in read.await_args_list)
    assert "x IN inbox |" in samples_query
    assert "x IN rs |" not in samples_query
    assert "excluded_outside_count" in count_query


def test_movements_mil_aircraft_window(client):
    with patch("app.routers.timeline.read_query", new_callable=AsyncMock) as mock:
        mock.side_effect = [
            [{
                "icao24": "abc123", "callsign": "FORTE10", "type_code": "RQ4",
                "military_branch": "USAF", "registration": None,
                "points": [
                    {"ts_ms": 1714521600000, "lat": 50.0, "lon": 30.0,
                     "altitude_m": 18000.0, "speed_ms": 200.0, "heading": 90.0},
                ],
            }],
            [{"total": 1}],  # count query (tracks, not points)
        ]
        resp = client.get(
            f"/api/timeline/window{W}&domain=movements&tier=fine&movement_kind=mil_aircraft"
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["domain"] == "movements"
    s = data["samples"][0]
    assert s["kind"] == "track" and s["icao24"] == "abc123"
    assert s["points"][0]["ts_ms"] == 1714521600000
    assert data["total_count"] == 1  # counts TRACKS not points
    assert data["truncated"] is False


_TRK = {
    "icao24": "a", "callsign": None, "type_code": None, "military_branch": None,
    "registration": None, "points": [{"ts_ms": 1, "lat": 0.0, "lon": 0.0}],
}


def test_movements_truncated_uses_pre_limit_count(client):
    # 2 tracks returned (limit hit) but the true match count is 5 -> truncated.
    with patch("app.routers.timeline.read_query", new_callable=AsyncMock) as mock:
        mock.side_effect = [[_TRK, _TRK], [{"total": 5}]]
        resp = client.get(
            f"/api/timeline/window{W}&domain=movements&tier=fine&movement_kind=mil_aircraft&limit=2"
        )
    data = resp.json()
    assert data["total_count"] == 5 and data["truncated"] is True


def test_movements_not_truncated_when_count_equals_returned(client):
    # exactly `limit` tracks and nothing dropped -> NOT truncated (total > len is False).
    with patch("app.routers.timeline.read_query", new_callable=AsyncMock) as mock:
        mock.side_effect = [[_TRK, _TRK], [{"total": 2}]]
        resp = client.get(
            f"/api/timeline/window{W}&domain=movements&tier=fine&movement_kind=mil_aircraft&limit=2"
        )
    data = resp.json()
    assert data["total_count"] == 2 and data["truncated"] is False


def test_movements_bbox_antimeridian_plumbing(client):
    with patch("app.routers.timeline.read_query", new_callable=AsyncMock) as mock:
        mock.side_effect = [[], [{"total": 0}]]
        resp = client.get(
            f"/api/timeline/window{W}&domain=movements&tier=fine"
            "&movement_kind=mil_aircraft&bbox=170,-10,-170,10"
        )
    assert resp.status_code == 200
    assert resp.json()["bbox"] == {"west": 170.0, "south": -10.0, "east": -170.0, "north": 10.0}


def test_events_neo4j_down_503(client):
    with patch("app.routers.timeline.read_query", new_callable=AsyncMock) as mock:
        mock.side_effect = RuntimeError("boom")
        resp = client.get(f"/api/timeline/window{W}")
    assert resp.status_code == 503


def test_movements_neo4j_down_503(client):
    with patch("app.routers.timeline.read_query", new_callable=AsyncMock) as mock:
        mock.side_effect = RuntimeError("boom")
        resp = client.get(
            f"/api/timeline/window{W}&domain=movements&tier=fine&movement_kind=mil_aircraft"
        )
    assert resp.status_code == 503


@pytest.mark.parametrize("kind", ["civil_aircraft", "ship", "satellite"])
def test_movements_unimplemented_kinds_501(client, kind):
    resp = client.get(
        f"/api/timeline/window{W}&domain=movements&tier=fine&movement_kind={kind}"
    )
    assert resp.status_code == 501


def test_window_mixed_naive_tz_reversed_422(client):
    resp = client.get(
        "/api/timeline/window?t_start=2026-05-02T00:00:00Z&t_end=2026-05-01T00:00:00"
    )
    assert resp.status_code == 422


def test_movements_missing_kind_422(client):
    resp = client.get(f"/api/timeline/window{W}&domain=movements&tier=fine")
    assert resp.status_code == 422


def test_movements_coarse_422(client):
    resp = client.get(f"/api/timeline/window{W}&domain=movements&movement_kind=mil_aircraft")
    assert resp.status_code == 422  # tier defaults to coarse


def test_movements_civil_501(client):
    resp = client.get(
        f"/api/timeline/window{W}&domain=movements&tier=fine&movement_kind=civil_aircraft"
    )
    assert resp.status_code == 501


def test_movements_unknown_kind_422(client):
    resp = client.get(
        f"/api/timeline/window{W}&domain=movements&tier=fine&movement_kind=bicycle"
    )
    assert resp.status_code == 422
