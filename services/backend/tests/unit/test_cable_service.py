"""Unit tests for submarine cable models and service."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from app.models.cable import CableDataset, LandingPoint, SubmarineCable
from app.services.cable_service import (
    _load_fallback,
    _parse_cables,
    _parse_capacity,
    _parse_color,
    _parse_landing_points,
    _parse_length,
    get_cable_dataset,
)


class TestSubmarineCableModel:
    def test_minimal_cable(self) -> None:
        cable = SubmarineCable(
            id="abc",
            name="Test Cable",
            coordinates=[[[0.0, 1.0], [2.0, 3.0]]],
        )
        assert cable.id == "abc"
        assert cable.color == "#00bcd4"
        assert cable.is_planned is False
        assert cable.landing_point_ids == []

    def test_full_cable(self) -> None:
        cable = SubmarineCable(
            id="xyz",
            name="Trans-Atlantic",
            color="#ff6600",
            is_planned=True,
            owners="Google, Meta",
            capacity_tbps=400.0,
            length_km=6500.0,
            rfs="2027",
            url="https://example.com",
            landing_point_ids=["lp1", "lp2"],
            coordinates=[[[10.0, 20.0], [30.0, 40.0]], [[50.0, 60.0], [70.0, 80.0]]],
        )
        assert cable.is_planned is True
        assert cable.capacity_tbps == 400.0
        assert len(cable.coordinates) == 2

    def test_cable_missing_required_fields(self) -> None:
        with pytest.raises(ValidationError):
            SubmarineCable(id="x", name="Y")  # type: ignore[call-arg]  # missing coordinates

    def test_landing_point(self) -> None:
        lp = LandingPoint(
            id="lp1", name="Marseille", country="France", latitude=43.3, longitude=5.4
        )
        assert lp.country == "France"

    def test_cable_dataset(self) -> None:
        ds = CableDataset(
            cables=[SubmarineCable(id="c1", name="C", coordinates=[[[0, 0], [1, 1]]])],
            landing_points=[LandingPoint(id="lp1", name="LP", latitude=0, longitude=0)],
            source="live",
        )
        assert ds.source == "live"
        assert len(ds.cables) == 1

    @pytest.mark.parametrize(
        "coordinates",
        [[], [[[float("nan"), 1], [2, 3]]], [[[181, 0], [2, 3]]]],
    )
    def test_invalid_cached_geometry_is_rejected(
        self, coordinates: list[list[list[float]]]
    ) -> None:
        with pytest.raises(ValidationError):
            SubmarineCable(id="bad", name="Bad", coordinates=coordinates)

    def test_dataset_source_is_restricted_but_empty_data_is_valid(self) -> None:
        assert CableDataset(cables=[], landing_points=[], source="live").cables == []
        with pytest.raises(ValidationError):
            CableDataset(cables=[], landing_points=[], source="unknown")  # type: ignore[arg-type]

    def test_mutable_default_isolation(self) -> None:
        a = SubmarineCable(id="a", name="A", coordinates=[[[0, 0], [1, 1]]])
        b = SubmarineCable(id="b", name="B", coordinates=[[[0, 0], [1, 1]]])
        a.landing_point_ids.append("x")
        assert b.landing_point_ids == []


class TestParsers:
    def test_parse_length_normal(self) -> None:
        assert _parse_length("1234") == 1234.0

    def test_parse_length_with_comma_and_unit(self) -> None:
        assert _parse_length("1,234 km") == 1234.0

    def test_parse_length_none(self) -> None:
        assert _parse_length(None) is None

    def test_parse_length_garbage(self) -> None:
        assert _parse_length("not a number") is None

    def test_parse_capacity_normal(self) -> None:
        assert _parse_capacity("400") == 400.0

    def test_parse_capacity_with_unit(self) -> None:
        assert _parse_capacity("200 Tbps") == 200.0

    def test_parse_capacity_none(self) -> None:
        assert _parse_capacity(None) is None

    def test_parse_color_valid(self) -> None:
        assert _parse_color("#ff6600") == "#ff6600"

    def test_parse_color_invalid(self) -> None:
        assert _parse_color("not-a-color") == "#00bcd4"

    def test_parse_color_none(self) -> None:
        assert _parse_color(None) == "#00bcd4"

    def test_parse_color_short_hex(self) -> None:
        assert _parse_color("#f60") == "#f60"

    def test_explicit_units_and_invalid_numeric_values(self) -> None:
        assert _parse_capacity("12 Gbps") == pytest.approx(0.012)
        assert _parse_length("500 nmi") == pytest.approx(926.0)
        assert _parse_capacity("12 widgets") is None
        assert _parse_length("500 furlongs") is None
        for bad in (-1, float("nan"), float("inf"), True):
            assert _parse_capacity(bad) is None
            assert _parse_length(bad) is None

    @pytest.mark.parametrize("raw", [True, "true", "TRUE", 1, "1"])
    def test_planned_true_values(self, raw: object) -> None:
        geo = {"features": [{
            "properties": {"id": "5", "name": "P", "is_planned": raw},
            "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
        }]}
        assert _parse_cables(geo)[0].is_planned is True

    @pytest.mark.parametrize("raw", [False, "false", "FALSE", 0, "0", None])
    def test_planned_false_values(self, raw: object) -> None:
        geo = {"features": [{
            "properties": {"id": "5", "name": "P", "is_planned": raw},
            "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
        }]}
        assert _parse_cables(geo)[0].is_planned is False


class TestParseCables:
    def test_poison_feature_is_skipped_without_logger_failure(self) -> None:
        geo = {"features": [None, {
            "properties": {"id": "good", "name": "Good"},
            "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
        }]}
        cables = _parse_cables(geo)
        assert [cable.id for cable in cables] == ["good"]

    @pytest.mark.parametrize("broken", [
        {"properties": None, "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}},
        {"properties": {"id": "bad", "name": "Bad"}, "geometry": None},
    ])
    def test_null_properties_or_geometry_is_isolated(self, broken: dict[str, object]) -> None:
        good = {
            "properties": {"id": "good", "name": "Good"},
            "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
        }
        cables = _parse_cables({"features": [good, broken]})
        assert [cable.id for cable in cables] == ["good"]

    @pytest.mark.parametrize("bad_root", [{}, {"features": None}, []])
    def test_malformed_geojson_root_is_not_valid_empty_data(self, bad_root: object) -> None:
        with pytest.raises(ValueError):
            _parse_cables(bad_root)  # type: ignore[arg-type]

    def test_invalid_segment_is_removed_without_null_island(self) -> None:
        geo = {"features": [{
            "properties": {"id": "1", "name": "C"},
            "geometry": {"type": "MultiLineString", "coordinates": [
                [[0, 0], [1, 1]], [[float("nan"), 2], [3, 4]],
                [[10**400, 2], [3, 4]],
            ]},
        }]}
        cable = _parse_cables(geo)[0]
        assert cable.coordinates == [[[0, 0], [1, 1]]]

    def test_nonfinite_third_coordinate_only_removes_that_segment(self) -> None:
        geo = {"features": [{
            "properties": {"id": "1", "name": "C"},
            "geometry": {"type": "MultiLineString", "coordinates": [
                [[0, 0], [1, 1]], [[2, 2, float("nan")], [3, 3, 4]],
            ]},
        }]}
        cable = _parse_cables(geo)[0]
        assert cable.coordinates == [[[0, 0], [1, 1]]]

    def test_multilinestring(self) -> None:
        geo = {
            "features": [
                {
                    "properties": {"id": "1", "name": "Test", "color": "#aabbcc"},
                    "geometry": {"type": "MultiLineString", "coordinates": [[[0, 1], [2, 3]]]},
                }
            ]
        }
        cables = _parse_cables(geo)
        assert len(cables) == 1
        assert cables[0].name == "Test"

    def test_linestring_normalized(self) -> None:
        geo = {
            "features": [
                {
                    "properties": {"id": "2", "name": "LS"},
                    "geometry": {"type": "LineString", "coordinates": [[0, 1], [2, 3]]},
                }
            ]
        }
        cables = _parse_cables(geo)
        assert len(cables) == 1
        assert cables[0].coordinates == [[[0, 1], [2, 3]]]

    def test_skip_missing_coordinates(self) -> None:
        geo = {
            "features": [
                {"properties": {"id": "3", "name": "X"}, "geometry": {"type": "MultiLineString"}}
            ]
        }
        with pytest.raises(ValueError):
            _parse_cables(geo)

    def test_skip_unknown_geometry_type(self) -> None:
        geo = {
            "features": [
                {
                    "properties": {"id": "4"},
                    "geometry": {"type": "Polygon", "coordinates": [[[0, 1]]]},
                }
            ]
        }
        with pytest.raises(ValueError):
            _parse_cables(geo)

    def test_is_planned_flag(self) -> None:
        geo = {
            "features": [
                {
                    "properties": {"id": "5", "name": "P", "is_planned": True},
                    "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
                }
            ]
        }
        assert _parse_cables(geo)[0].is_planned is True


class TestParseLandingPoints:
    def test_valid_point(self) -> None:
        geo = {
            "features": [
                {
                    "properties": {"id": "lp1", "name": "Marseille", "country": "France"},
                    "geometry": {"type": "Point", "coordinates": [5.4, 43.3]},
                }
            ]
        }
        pts = _parse_landing_points(geo)
        assert len(pts) == 1
        assert pts[0].latitude == 43.3
        assert pts[0].longitude == 5.4

    def test_skip_non_point(self) -> None:
        geo = {
            "features": [
                {
                    "properties": {"id": "x"},
                    "geometry": {"type": "LineString", "coordinates": [[0, 0]]},
                }
            ]
        }
        with pytest.raises(ValueError):
            _parse_landing_points(geo)

    def test_optional_owner_field_is_filtered_and_valid_cable_retained(self) -> None:
        geo = {"features": [{
            "properties": {
                "id": "1", "name": "Cable", "owners": [" A ", None, 5, ""],
                "landing_points": ["lp1", None, 9],
            },
            "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
        }]}
        cable = _parse_cables(geo)[0]
        assert cable.owners == "A"
        assert cable.landing_point_ids == ["lp1", "9"]

    def test_coordinate_string_does_not_create_landing_point(self) -> None:
        geo = {"features": [{
            "properties": {"id": "lp", "name": "Invalid"},
            "geometry": {"type": "Point", "coordinates": "12"},
        }]}
        with pytest.raises(ValueError):
            _parse_landing_points(geo)

    def test_overflowing_bad_coordinate_does_not_discard_valid_neighbor(self) -> None:
        geo = {"features": [
            {
                "properties": {"id": "bad", "name": "Invalid"},
                "geometry": {"type": "Point", "coordinates": [10**400, 2]},
            },
            {
                "properties": {"id": "good", "name": "Good"},
                "geometry": {"type": "Point", "coordinates": [1, 2]},
            },
        ]}
        assert [point.id for point in _parse_landing_points(geo)] == ["good"]

    def test_unknown_planned_flag_defaults_false(self) -> None:
        geo = {"features": [{
            "properties": {"id": "1", "name": "Cable", "is_planned": "perhaps"},
            "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
        }]}
        assert _parse_cables(geo)[0].is_planned is False

    def test_unusable_optional_rfs_is_null(self) -> None:
        for rfs in ({"year": 2030}, True):
            geo = {"features": [{
                "properties": {"id": "1", "name": "Cable", "rfs": rfs},
                "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
            }]}
            assert _parse_cables(geo)[0].rfs is None


class TestFallback:
    def test_fallback_returns_dataset(self) -> None:
        ds = _load_fallback()
        assert ds.source == "fallback"
        assert isinstance(ds.cables, list)

    def test_fallback_missing_file(self) -> None:
        with patch("app.services.cable_service.FALLBACK_PATH") as mock_path:
            mock_path.read_text.side_effect = FileNotFoundError
            ds = _load_fallback()
            assert ds.source == "fallback"
            assert ds.cables == []

    def test_fallback_parses_raw_geojson(self) -> None:
        raw = json.dumps({
            "cables_geojson": {
                "features": [
                    {
                        "properties": {"id": "1", "name": "FB"},
                        "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
                    }
                ]
            },
            "landing_points_geojson": {
                "features": [
                    {
                        "properties": {"id": "lp1", "name": "LP"},
                        "geometry": {"type": "Point", "coordinates": [5.0, 43.0]},
                    }
                ]
            },
        })
        with patch("app.services.cable_service.FALLBACK_PATH") as mock_path:
            mock_path.read_text.return_value = raw
            ds = _load_fallback()
            assert len(ds.cables) == 1
            assert len(ds.landing_points) == 1
            assert ds.cables[0].name == "FB"


class TestGetCableDataset:
    @pytest.mark.asyncio
    async def test_cache_hit(self) -> None:
        cache = AsyncMock()
        cache.get.return_value = {"cables": [], "landing_points": [], "source": "live"}
        proxy = AsyncMock()

        ds = await get_cable_dataset(proxy, cache)
        assert ds.source == "live"
        proxy.get_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_miss_live_fetch(self) -> None:
        cache = AsyncMock()
        cache.get.return_value = None
        proxy = AsyncMock()
        proxy.get_json.side_effect = [
            {
                "features": [
                    {
                        "properties": {"id": "1", "name": "C"},
                        "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
                    }
                ]
            },
            {"features": []},
        ]

        ds = await get_cable_dataset(proxy, cache)
        assert ds.source == "live"
        assert len(ds.cables) == 1
        cache.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_structurally_valid_empty_live_dataset_remains_live(self) -> None:
        cache = AsyncMock()
        cache.get.return_value = None
        proxy = AsyncMock()
        proxy.get_json.side_effect = [{"features": []}, {"features": []}]
        dataset = await get_cable_dataset(proxy, cache)
        assert dataset.source == "live"
        assert dataset.cables == []
        assert dataset.landing_points == []

    @pytest.mark.asyncio
    async def test_cache_miss_live_fails_uses_fallback(self) -> None:
        cache = AsyncMock()
        cache.get.return_value = None
        proxy = AsyncMock()
        proxy.get_json.side_effect = Exception("network error")

        ds = await get_cable_dataset(proxy, cache)
        assert ds.source == "fallback"

    @pytest.mark.asyncio
    async def test_corrupt_cache_is_deleted_and_refreshed_from_live(self) -> None:
        cache = AsyncMock()
        cache.get.return_value = []
        proxy = AsyncMock()
        proxy.get_json.side_effect = [
            {"features": [{
                "properties": {"id": "1", "name": "Live"},
                "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
            }]},
            {"features": []},
        ]
        dataset = await get_cable_dataset(proxy, cache)
        assert dataset.source == "live"
        assert [cable.id for cable in dataset.cables] == ["1"]
        cache.delete.assert_awaited_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("corrupt", [
        [],
        {"cables": [], "source": "live"},
        {"cables": [{"id": "bad"}], "landing_points": [], "source": "live"},
    ])
    async def test_corrupt_cache_shapes_are_deleted_and_refreshed(self, corrupt: object) -> None:
        cache = AsyncMock()
        cache.get.return_value = corrupt
        proxy = AsyncMock()
        proxy.get_json.side_effect = [{"features": []}, {"features": []}]
        dataset = await get_cable_dataset(proxy, cache)
        assert dataset.source == "live"
        assert dataset.cables == []
        cache.delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_mixed_live_features_keep_valid_cable_neighbors(self) -> None:
        cache = AsyncMock()
        cache.get.return_value = None
        proxy = AsyncMock()
        good = {
            "properties": {"id": "good", "name": "Good"},
            "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
        }
        proxy.get_json.side_effect = [
            {"features": [good, None, {
                "properties": None,
                "geometry": {"type": "LineString", "coordinates": [[2, 2], [3, 3]]},
            }, good | {"properties": {"id": "good-2", "name": "Good 2"}}]},
            {"features": []},
        ]
        dataset = await get_cable_dataset(proxy, cache)
        assert dataset.source == "live"
        assert [cable.id for cable in dataset.cables] == ["good", "good-2"]
