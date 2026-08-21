"""Static, catalog-backed CHRONIK spatial-filter compilation tests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.spatial import CatalogProblemCode, ScopeKind, SpatialCatalogProblem
from app.services.spatial_filters import (
    GeoExtent,
    LongitudeSpan,
    TimelineSpatialQueryId,
    compile_extent_filter,
    extent_from_boundary_geometry,
    resolve_catalog_filter,
)

CATALOG_A = "spatial-v1-aaaaaaaaaaaa"
CATALOG_B = "spatial-v1-bbbbbbbbbbbb"
DERIVATION_A = "spatial-derive-v1-aaaaaaaaaaaa"
DERIVATION_B = "spatial-derive-v1-bbbbbbbbbbbb"


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
