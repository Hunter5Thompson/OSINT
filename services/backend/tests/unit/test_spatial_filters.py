"""Static, catalog-backed CHRONIK spatial-filter compilation tests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.spatial import (
    CatalogProblemCode,
    ScopeKind,
    SpatialCatalogProblem,
    SpatialScopeTokenV1,
)
from app.models.timeline import (
    ChronikExactSpatialActivationV1,
    ChronikSpatialLane,
)
from app.services.spatial_filters import (
    EventSpatialRelation,
    ExactActivationRejectionCause,
    GeoExtent,
    LongitudeSpan,
    ResolvedSpatialConstraint,
    TimelineSpatialQueryId,
    UnsupportedExactSpatialQueryError,
    compile_exact_event_query_plan,
    compile_extent_filter,
    exact_event_parameters,
    exact_event_query_templates,
    extent_from_boundary_geometry,
    parse_exact_event_accounting,
    resolve_catalog_filter,
    select_exact_event_activation,
)

CATALOG_A = "spatial-v1-aaaaaaaaaaaa"
CATALOG_B = "spatial-v1-bbbbbbbbbbbb"
DERIVATION_A = "spatial-derive-v1-aaaaaaaaaaaa"
DERIVATION_B = "spatial-derive-v1-bbbbbbbbbbbb"


_EXACT_SCOPE_PROPERTY = {
    ScopeKind.COUNTRY: "country_scope_key",
    ScopeKind.ADMIN1: "admin1_scope_key",
    ScopeKind.ADMIN2: "admin2_scope_key",
}


@pytest.mark.parametrize("scope_kind", tuple(_EXACT_SCOPE_PROPERTY))
def test_exact_event_occurrence_contract_excludes_conflicts_and_binds_identity(
    scope_kind: ScopeKind,
):
    """Legacy conflicts remain unsafe unless every exact template filters them."""

    templates = exact_event_query_templates(
        scope_kind,
        EventSpatialRelation.OCCURS_IN,
    )
    property_name = _EXACT_SCOPE_PROPERTY[scope_kind]

    for query in (templates.samples, templates.count):
        assert f"l.{property_name} = $scope_key" in query
        assert "l.spatial_derivation_revision IN $compatible_revisions" in query
        assert "l.spatial_conflict = false" in query
        assert "country:UKR" not in query
        assert DERIVATION_A not in query

    # A conflict can carry the same key and compatible revision as a valid Location.
    # The explicit boolean predicate, not revision nullability, is the exclusion gate.
    matching_locations = [
        {"scope_key": "country:UKR", "revision": DERIVATION_A, "conflict": False},
        {"scope_key": "country:UKR", "revision": DERIVATION_A, "conflict": True},
    ]
    included = [
        location
        for location in matching_locations
        if location["scope_key"] == "country:UKR"
        and location["revision"] in (DERIVATION_A,)
        and location["conflict"] is False
    ]
    assert included == [matching_locations[0]]


@pytest.mark.parametrize("scope_kind", tuple(_EXACT_SCOPE_PROPERTY))
def test_exact_event_occurrence_collapses_duplicate_locations_before_limit(
    scope_kind: ScopeKind,
):
    templates = exact_event_query_templates(
        scope_kind,
        EventSpatialRelation.OCCURS_IN,
    )

    collapse = "WITH ev, collect(l)[0] AS l"
    assert collapse in templates.samples
    assert templates.samples.index(collapse) < templates.samples.index("LIMIT $limit")
    assert "count(DISTINCT ev) AS included_count" in templates.count

    # Fixture shape: ev-1 has two equally matching OCCURRED_AT Locations. The static
    # collapse contract must yield one top-level row and consume one unit of LIMIT.
    matches = [("ev-1", "location-a"), ("ev-1", "location-b"), ("ev-2", "location-c")]
    distinct_events = list(dict.fromkeys(event_id for event_id, _ in matches))
    assert distinct_events[:2] == ["ev-1", "ev-2"]


def test_exact_event_registry_is_closed_and_antimeridian_independent():
    queries = {
        kind: exact_event_query_templates(kind, EventSpatialRelation.OCCURS_IN)
        for kind in _EXACT_SCOPE_PROPERTY
    }

    assert set(queries) == {ScopeKind.COUNTRY, ScopeKind.ADMIN1, ScopeKind.ADMIN2}
    for scope_kind, templates in queries.items():
        expected_property = _EXACT_SCOPE_PROPERTY[scope_kind]
        other_properties = set(_EXACT_SCOPE_PROPERTY.values()) - {expected_property}
        combined = f"{templates.samples}\n{templates.count}"
        assert all(f"l.{name}" not in combined for name in other_properties)
        assert all(
            parameter not in combined
            for parameter in ("$west", "$east", "$south", "$north", "$bbox_off")
        )

    with pytest.raises(UnsupportedExactSpatialQueryError):
        exact_event_query_templates(ScopeKind.WORLD, EventSpatialRelation.OCCURS_IN)
    with pytest.raises(UnsupportedExactSpatialQueryError):
        exact_event_query_templates(ScopeKind.COUNTRY, EventSpatialRelation.INTERSECTS)
    with pytest.raises(UnsupportedExactSpatialQueryError):
        exact_event_query_templates("district", EventSpatialRelation.OCCURS_IN)  # type: ignore[arg-type]


@pytest.mark.parametrize("scope_kind", tuple(_EXACT_SCOPE_PROPERTY))
def test_exact_accounting_templates_partition_distinct_event_exclusions(
    scope_kind: ScopeKind,
):
    query = exact_event_query_templates(
        scope_kind,
        EventSpatialRelation.OCCURS_IN,
    ).count
    property_name = _EXACT_SCOPE_PROPERTY[scope_kind]

    assert query.count("count(DISTINCT ev)") == 4
    assert f"l.{property_name} = $scope_key" in query
    assert "l.spatial_conflict = true" in query
    assert "l.spatial_conflict = false" in query
    assert "l.spatial_derivation_revision IN $compatible_revisions" in query
    assert "NOT l.spatial_derivation_revision IN $compatible_revisions" in query
    for field in (
        "included_count",
        "excluded_unlocated_count",
        "excluded_conflict_count",
        "excluded_stale_revision_count",
        "excluded_unsupported_count",
        "total",
    ):
        assert field in query


async def test_exact_parameters_are_pinned_to_the_resolved_token_not_bbox_or_alias():
    resolved = _resolved(
        revision=CATALOG_A,
        scope_key="country:UKR",
        kind=ScopeKind.COUNTRY,
        derivation=DERIVATION_A,
        parent_key="world",
        containment_asset_id="asset-a",
    )
    loader = _FakeLoader({CATALOG_A: resolved})
    loader.asset_payloads["asset-a"] = _geometry([_box(20, 40, 41, 53)])

    # Resolution remains async and catalog-pinned; compilation only consumes its token.
    compiled = await resolve_catalog_filter(loader, "country:ukr", CATALOG_A)
    assert not isinstance(compiled, SpatialCatalogProblem)
    exact = compile_exact_event_query_plan(
        compiled,
        coverage_revision="coverage-a",
        coverage_complete=True,
    )
    parameters = exact_event_parameters(
        exact,
        t_start="2026-05-01T00:00:00Z",
        t_end="2026-05-02T00:00:00Z",
        limit=25,
    )

    assert parameters == {
        "scope_key": "country:UKR",
        "compatible_revisions": [DERIVATION_A],
        "t_start": "2026-05-01T00:00:00Z",
        "t_end": "2026-05-02T00:00:00Z",
        "limit": 25,
    }
    assert {"west", "east", "south", "north", "bbox_off"}.isdisjoint(parameters)


def test_exact_accounting_distinguishes_samples_and_reconciles_all_categories():
    accounting = parse_exact_event_accounting(
        [{
            "total": 10,
            "included_count": 3,
            "excluded_unlocated_count": 2,
            "excluded_conflict_count": 1,
            "excluded_stale_revision_count": 3,
            "excluded_unsupported_count": 1,
        }],
        sample_count=2,
    )

    assert accounting.total == 10
    assert accounting.included_count == 3
    assert accounting.sample_count == 2
    assert accounting.excluded_unlocated_count == 2
    assert accounting.excluded_conflict_count == 1
    assert accounting.excluded_stale_revision_count == 3
    assert accounting.excluded_unsupported_count == 1

    with pytest.raises(ValueError, match="reconcile"):
        parse_exact_event_accounting(
            [{
                "total": 11,
                "included_count": 3,
                "excluded_unlocated_count": 2,
                "excluded_conflict_count": 1,
                "excluded_stale_revision_count": 3,
                "excluded_unsupported_count": 1,
            }],
            sample_count=2,
        )


def _gate_filter(
    *,
    scope_kind: ScopeKind = ScopeKind.COUNTRY,
    catalog_revision: str = CATALOG_A,
    derivation_revision: str = DERIVATION_A,
):
    scope_key = {
        ScopeKind.COUNTRY: "country:UKR",
        ScopeKind.ADMIN1: "admin1:iso3166-2:UA-14",
        ScopeKind.ADMIN2: "admin2:geoboundaries:UKR.ADM2.1",
    }[scope_kind]
    token = SpatialScopeTokenV1(
        scope_key=scope_key,
        kind=scope_kind,
        catalog_revision=catalog_revision,
        derivation_revision=derivation_revision,
        boundary_policy="odin-reference-v1",
        compatible_derivation_revisions=(derivation_revision,),
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
            admin1_scope_key=(scope_key if scope_kind is ScopeKind.ADMIN1 else None),
            admin2_scope_key=(scope_key if scope_kind is ScopeKind.ADMIN2 else None),
        ),
    )


def _activation(**overrides: object) -> ChronikExactSpatialActivationV1:
    payload = {
        "lane": "event_occurrence",
        "scope_kind": "country",
        "catalog_revision": CATALOG_A,
        "derivation_revision": DERIVATION_A,
        "coverage_revision": "coverage-fixture-a",
        "enabled": True,
        "coverage_complete": True,
        "index_plan_verified": True,
        "stale_revision_ratio": 0.0,
        **overrides,
    }
    return ChronikExactSpatialActivationV1.model_validate(payload)


def test_exact_activation_selects_only_a_fully_eligible_lane_kind_revision():
    decision = select_exact_event_activation(
        _gate_filter(),
        lane=ChronikSpatialLane.EVENT_OCCURRENCE,
        activations=(_activation(),),
    )

    assert decision.plan is not None
    assert decision.cause is None
    assert decision.plan.coverage_revision == "coverage-fixture-a"
    assert decision.plan.coverage_complete is True


@pytest.mark.parametrize(
    ("activations", "spatial_filter", "lane", "expected_cause"),
    [
        ((), _gate_filter(), ChronikSpatialLane.EVENT_OCCURRENCE, "default_off"),
        (
            (_activation(scope_kind="admin1"),),
            _gate_filter(),
            ChronikSpatialLane.EVENT_OCCURRENCE,
            "lane_kind_not_allowlisted",
        ),
        (
            (_activation(enabled=False),),
            _gate_filter(),
            ChronikSpatialLane.EVENT_OCCURRENCE,
            "disabled",
        ),
        (
            (_activation(coverage_complete=False),),
            _gate_filter(),
            ChronikSpatialLane.EVENT_OCCURRENCE,
            "coverage_incomplete",
        ),
        (
            (_activation(index_plan_verified=False),),
            _gate_filter(),
            ChronikSpatialLane.EVENT_OCCURRENCE,
            "index_plan_unverified",
        ),
        (
            (_activation(stale_revision_ratio=0.0101),),
            _gate_filter(),
            ChronikSpatialLane.EVENT_OCCURRENCE,
            "stale_revision_coverage",
        ),
        (
            (_activation(),),
            _gate_filter(catalog_revision=CATALOG_B),
            ChronikSpatialLane.EVENT_OCCURRENCE,
            "catalog_revision_mismatch",
        ),
        (
            (_activation(),),
            _gate_filter(derivation_revision=DERIVATION_B),
            ChronikSpatialLane.EVENT_OCCURRENCE,
            "derivation_revision_mismatch",
        ),
        (
            (_activation(),),
            _gate_filter(),
            ChronikSpatialLane.MOVEMENT_TRACK,
            "unsupported_lane",
        ),
    ],
)
def test_exact_activation_rejections_are_explicit_and_return_the_bbox_plan(
    activations,
    spatial_filter,
    lane,
    expected_cause,
):
    decision = select_exact_event_activation(
        spatial_filter,
        lane=lane,
        activations=activations,
    )

    assert decision.plan is None
    assert decision.cause is ExactActivationRejectionCause(expected_cause)


def test_exact_activation_rollback_removes_the_plan_without_unfiltering():
    spatial_filter = _gate_filter()

    active = select_exact_event_activation(
        spatial_filter,
        lane=ChronikSpatialLane.EVENT_OCCURRENCE,
        activations=(_activation(),),
    )
    rolled_back = select_exact_event_activation(
        spatial_filter,
        lane=ChronikSpatialLane.EVENT_OCCURRENCE,
        activations=(),
    )

    assert active.plan is not None
    assert rolled_back.plan is None
    assert rolled_back.approximate_filter is spatial_filter
    assert rolled_back.approximate_filter.query_id is TimelineSpatialQueryId.BBOX_SINGLE


def _geometry(polygons: object) -> bytes:
    return json.dumps(
        {
            "schema_version": 1,
            "geometry_type": "MultiPolygon",
            "polygons": polygons,
        },
        separators=(",", ":"),
    ).encode()


def _box(west: float, south: float, east: float, north: float) -> list[object]:
    return [
        [
            [west, south],
            [east, south],
            [east, north],
            [west, north],
            [west, south],
        ]
    ]


@dataclass(frozen=True)
class _Descriptor:
    asset_id: str


def _resolved(
    *,
    revision: str,
    scope_key: str,
    kind: ScopeKind,
    derivation: str,
    parent_key: str | None,
    containment_asset_id: str | None,
) -> SimpleNamespace:
    scope = SimpleNamespace(key=scope_key, kind=kind, parent_key=parent_key)
    presentation = SimpleNamespace(
        containment=(
            _Descriptor(containment_asset_id)
            if containment_asset_id is not None
            else None
        ),
        preferred_lod=None,
        outline_lods={},
        children_lods={},
    )
    record = SimpleNamespace(
        scope=scope,
        presentation=presentation,
        derivation_revision=derivation,
        compatible_derivation_revisions=(derivation,),
        path=("world", scope_key) if scope_key != "world" else ("world",),
    )
    path = (
        SimpleNamespace(key="world", kind=ScopeKind.WORLD),
        *(() if scope_key == "world" else (scope,)),
    )
    return SimpleNamespace(
        catalog_revision=revision,
        boundary_policy="odin-reference-v1",
        canonicalized_from=None,
        record=record,
        path=path,
    )


class _FakeLoader:
    def __init__(self, resolved_by_revision: dict[str, object]) -> None:
        self.resolved_by_revision = resolved_by_revision
        self.resolve_calls: list[tuple[str | None, str | None]] = []
        self.scope_records: dict[tuple[str, str], object] = {}
        self.asset_payloads: dict[str, bytes | SpatialCatalogProblem] = {}
        self.read_asset = AsyncMock(side_effect=self._read_asset)

    def resolve_scope(self, scope_key: str | None, revision: str | None) -> object:
        self.resolve_calls.append((scope_key, revision))
        assert revision is not None
        return self.resolved_by_revision[revision]

    def get_scope(self, revision: str, scope_key: str) -> object:
        return self.scope_records[(revision, scope_key)]

    def get_asset(self, revision: str, asset_id: str) -> object:
        assert revision in self.resolved_by_revision
        return SimpleNamespace(asset_id=asset_id, catalog_revision=revision)

    async def _read_asset(self, asset: SimpleNamespace) -> bytes | SpatialCatalogProblem:
        return self.asset_payloads[asset.asset_id]


def test_single_span_extent_compiles_to_fixed_parameterized_bbox_query():
    compiled = compile_extent_filter(
        GeoExtent(
            kind="segments",
            south=40,
            north=53,
            longitude=(LongitudeSpan(20, 41),),
        )
    )

    assert compiled.query_id is TimelineSpatialQueryId.BBOX_SINGLE
    assert compiled.parameters == {
        "bbox_off": False,
        "west": 20,
        "east": 41,
        "south": 40,
        "north": 53,
    }
    assert compiled.bbox is not None
    assert compiled.bbox.west == 20
    assert compiled.bbox.east == 41


def test_fiji_two_spans_project_to_legacy_wrapping_bbox_without_losing_dateline():
    compiled = compile_extent_filter(
        GeoExtent(
            kind="segments",
            south=-18.3,
            north=-16.0,
            longitude=(
                LongitudeSpan(-180, -179.79),
                LongitudeSpan(177.28, 180),
            ),
        )
    )

    assert compiled.query_id is TimelineSpatialQueryId.BBOX_DATELINE
    assert compiled.bbox is not None
    assert (compiled.bbox.west, compiled.bbox.east) == (177.28, -179.79)
    assert compiled.parameters["west"] == 177.28
    assert compiled.parameters["east"] == -179.79


def test_non_global_polar_extent_preserves_full_longitude_with_limited_latitude():
    payload = _geometry(
        [
            [
                [
                    [-180, -90],
                    [180, -90],
                    [180, -80],
                    [-180, -80],
                    [-180, -90],
                ]
            ]
        ]
    )

    extent = extent_from_boundary_geometry(payload)
    compiled = compile_extent_filter(extent)

    assert extent == GeoExtent(
        kind="segments",
        south=-90,
        north=-80,
        longitude=(LongitudeSpan(-180, 180),),
    )
    assert compiled.query_id is TimelineSpatialQueryId.BBOX_SINGLE
    assert compiled.parameters["south"] == -90
    assert compiled.parameters["north"] == -80
    assert compiled.parameters["bbox_off"] is False


@pytest.mark.parametrize(
    "extent",
    [
        GeoExtent(
            kind="segments",
            south=-10,
            north=10,
            longitude=(LongitudeSpan(-30, -20), LongitudeSpan(20, 30)),
        ),
        GeoExtent(
            kind="segments",
            south=-10,
            north=10,
            longitude=(LongitudeSpan(20, 30), LongitudeSpan(-180, -170)),
        ),
    ],
)
def test_invalid_two_span_extent_is_never_guessed_into_a_bbox(extent: GeoExtent):
    with pytest.raises(ValueError, match="dateline"):
        compile_extent_filter(extent)


def test_world_extent_uses_explicit_global_query_and_no_magic_bbox():
    compiled = compile_extent_filter(GeoExtent(kind="world"))

    assert compiled.query_id is TimelineSpatialQueryId.GLOBAL
    assert compiled.bbox is None
    assert compiled.parameters == {
        "bbox_off": True,
        "west": -180.0,
        "east": 180.0,
        "south": -90.0,
        "north": 90.0,
    }


async def test_catalog_resolution_pins_active_and_previous_revision_tokens():
    active = _resolved(
        revision=CATALOG_A,
        scope_key="country:UKR",
        kind=ScopeKind.COUNTRY,
        derivation=DERIVATION_A,
        parent_key="world",
        containment_asset_id="asset-a",
    )
    previous = _resolved(
        revision=CATALOG_B,
        scope_key="country:UKR",
        kind=ScopeKind.COUNTRY,
        derivation=DERIVATION_B,
        parent_key="world",
        containment_asset_id="asset-b",
    )
    loader = _FakeLoader({CATALOG_A: active, CATALOG_B: previous})
    loader.asset_payloads = {
        "asset-a": _geometry([_box(20, 40, 41, 53)]),
        "asset-b": _geometry([_box(21, 41, 42, 54)]),
    }

    active_filter = await resolve_catalog_filter(loader, "country:UKR", CATALOG_A)
    previous_filter = await resolve_catalog_filter(loader, "country:UKR", CATALOG_B)

    assert not isinstance(active_filter, SpatialCatalogProblem)
    assert not isinstance(previous_filter, SpatialCatalogProblem)
    assert active_filter.constraint is not None
    assert previous_filter.constraint is not None
    assert active_filter.constraint.token.catalog_revision == CATALOG_A
    assert active_filter.constraint.token.derivation_revision == DERIVATION_A
    assert previous_filter.constraint.token.catalog_revision == CATALOG_B
    assert previous_filter.constraint.token.derivation_revision == DERIVATION_B
    assert loader.resolve_calls == [
        ("country:UKR", CATALOG_A),
        ("country:UKR", CATALOG_B),
    ]


async def test_catalog_world_token_resolves_without_reading_a_boundary_asset():
    resolved = _resolved(
        revision=CATALOG_A,
        scope_key="world",
        kind=ScopeKind.WORLD,
        derivation=DERIVATION_A,
        parent_key=None,
        containment_asset_id=None,
    )
    loader = _FakeLoader({CATALOG_A: resolved})

    compiled = await resolve_catalog_filter(loader, "world", CATALOG_A)

    assert not isinstance(compiled, SpatialCatalogProblem)
    assert compiled.query_id is TimelineSpatialQueryId.GLOBAL
    assert compiled.constraint is not None
    assert compiled.constraint.token.scope_key == "world"
    loader.read_asset.assert_not_awaited()


async def test_scope_without_direct_asset_resolves_exact_feature_from_parent_pack():
    resolved = _resolved(
        revision=CATALOG_A,
        scope_key="country:FJI",
        kind=ScopeKind.COUNTRY,
        derivation=DERIVATION_A,
        parent_key="world",
        containment_asset_id=None,
    )
    parent = SimpleNamespace(
        presentation=SimpleNamespace(
            preferred_lod="overview",
            children_lods={"overview": _Descriptor("world-pack")},
        )
    )
    pack = {
        "schema_version": 1,
        "parent_scope_key": "world",
        "features": [
            {
                "kind": "scope",
                "scope_key": "country:FJI",
                "label": "Fiji",
                "geometry": json.loads(
                    _geometry(
                        [
                            _box(-180, -18.3, -179.79, -16.0),
                            _box(177.28, -18.3, 180, -16.0),
                        ]
                    )
                ),
            },
            {
                "kind": "context",
                "feature_id": "ocean-context",
                "label": "Context",
                "non_scope_reason": "not navigable",
                "geometry": json.loads(_geometry([_box(0, 0, 1, 1)])),
            },
        ],
    }
    loader = _FakeLoader({CATALOG_A: resolved})
    loader.scope_records[(CATALOG_A, "world")] = parent
    loader.asset_payloads["world-pack"] = json.dumps(pack, separators=(",", ":")).encode()

    compiled = await resolve_catalog_filter(loader, "country:FJI", CATALOG_A)

    assert not isinstance(compiled, SpatialCatalogProblem)
    assert compiled.query_id is TimelineSpatialQueryId.BBOX_DATELINE
    assert compiled.bbox is not None
    assert (compiled.bbox.west, compiled.bbox.east) == (177.28, -179.79)


async def test_catalog_failure_is_returned_fail_closed_without_global_plan():
    problem = SpatialCatalogProblem(
        code=CatalogProblemCode.CATALOG_REVISION_UNAVAILABLE,
        message="Requested spatial catalog revision is not served",
        target=CATALOG_B,
        recoverable=True,
        active_catalog_revision=CATALOG_A,
    )
    loader = _FakeLoader({CATALOG_B: problem})

    result = await resolve_catalog_filter(loader, "country:UKR", CATALOG_B)

    assert result is problem
    loader.read_asset.assert_not_awaited()


async def test_invalid_catalog_geometry_returns_filter_unavailable_not_global():
    resolved = _resolved(
        revision=CATALOG_A,
        scope_key="country:UKR",
        kind=ScopeKind.COUNTRY,
        derivation=DERIVATION_A,
        parent_key="world",
        containment_asset_id="broken",
    )
    loader = _FakeLoader({CATALOG_A: resolved})
    loader.asset_payloads["broken"] = b'{"schema_version":1,"geometry_type":"Polygon"}'

    result = await resolve_catalog_filter(loader, "country:UKR", CATALOG_A)

    assert isinstance(result, SpatialCatalogProblem)
    assert result.code is CatalogProblemCode.SPATIAL_FILTER_UNAVAILABLE
