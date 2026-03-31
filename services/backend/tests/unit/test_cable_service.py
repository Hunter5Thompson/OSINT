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
