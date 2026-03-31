"""Unit tests for submarine cable models and service."""

import pytest
from pydantic import ValidationError

from app.models.cable import CableDataset, LandingPoint, SubmarineCable


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
        lp = LandingPoint(id="lp1", name="Marseille", country="France", latitude=43.3, longitude=5.4)
        assert lp.country == "France"

    def test_cable_dataset(self) -> None:
        ds = CableDataset(
            cables=[SubmarineCable(id="c1", name="C", coordinates=[[[0, 0], [1, 1]]])],
            landing_points=[LandingPoint(id="lp1", name="LP", latitude=0, longitude=0)],
            source="live",
        )
        assert ds.source == "live"
        assert len(ds.cables) == 1

    def test_mutable_default_isolation(self) -> None:
        a = SubmarineCable(id="a", name="A", coordinates=[[[0, 0], [1, 1]]])
        b = SubmarineCable(id="b", name="B", coordinates=[[[0, 0], [1, 1]]])
        a.landing_point_ids.append("x")
        assert b.landing_point_ids == []


import json
from unittest.mock import AsyncMock, patch

from app.services.cable_service import (
    _load_fallback,
    _parse_cables,
    _parse_capacity,
    _parse_color,
    _parse_landing_points,
    _parse_length,
    get_cable_dataset,
)


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


class TestParseCables:
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
        geo = {"features": [{"properties": {"id": "3", "name": "X"}, "geometry": {"type": "MultiLineString"}}]}
        assert _parse_cables(geo) == []

    def test_skip_unknown_geometry_type(self) -> None:
        geo = {"features": [{"properties": {"id": "4"}, "geometry": {"type": "Polygon", "coordinates": [[[0, 1]]]}}]}
        assert _parse_cables(geo) == []

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
        geo = {"features": [{"properties": {"id": "x"}, "geometry": {"type": "LineString", "coordinates": [[0, 0]]}}]}
        assert _parse_landing_points(geo) == []


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
                    {"properties": {"id": "1", "name": "FB"}, "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}}
                ]
            },
            "landing_points_geojson": {
                "features": [
                    {"properties": {"id": "lp1", "name": "LP"}, "geometry": {"type": "Point", "coordinates": [5.0, 43.0]}}
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
            {"features": [{"properties": {"id": "1", "name": "C"}, "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}}]},
            {"features": []},
        ]

        ds = await get_cable_dataset(proxy, cache)
        assert ds.source == "live"
        assert len(ds.cables) == 1
        cache.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_cache_miss_live_fails_uses_fallback(self) -> None:
        cache = AsyncMock()
        cache.get.return_value = None
        proxy = AsyncMock()
        proxy.get_json.side_effect = Exception("network error")

        ds = await get_cable_dataset(proxy, cache)
        assert ds.source == "fallback"
