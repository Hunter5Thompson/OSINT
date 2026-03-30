"""Tests for Neo4j graph Pydantic models."""

import pytest
from datetime import datetime, timezone
from graph.models import Entity, Event, Source, Location


class TestEntity:
    def test_defaults(self):
        e = Entity(name="NATO", type="organization")
        assert e.name == "NATO"
        assert e.type == "organization"
        assert e.confidence == 0.5
        assert e.aliases == []
        assert len(e.id) == 12

    def test_aliases_not_shared(self):
        a = Entity(name="A", type="person")
        b = Entity(name="B", type="person")
        a.aliases.append("x")
        assert b.aliases == []

    def test_valid_types(self):
        for t in ["person", "organization", "location", "weapon_system",
                   "satellite", "vessel", "aircraft", "military_unit"]:
            e = Entity(name="test", type=t)
            assert e.type == t

    def test_invalid_type_rejected(self):
        with pytest.raises(ValueError):
            Entity(name="test", type="invalid_type")

    def test_confidence_bounds(self):
        Entity(name="t", type="person", confidence=0.0)
        Entity(name="t", type="person", confidence=1.0)
        with pytest.raises(ValueError):
            Entity(name="t", type="person", confidence=1.1)
        with pytest.raises(ValueError):
            Entity(name="t", type="person", confidence=-0.1)


class TestEvent:
    def test_defaults(self):
        ev = Event(
            title="Drone Strike",
            timestamp=datetime(2026, 3, 30, tzinfo=timezone.utc),
            codebook_type="military.drone_attack",
            severity="high",
        )
        assert ev.title == "Drone Strike"
        assert ev.severity == "high"
        assert ev.confidence == 0.5
        assert ev.summary == ""
        assert len(ev.id) == 12

    def test_invalid_severity_rejected(self):
        with pytest.raises(ValueError):
            Event(
                title="t",
                timestamp=datetime.now(tz=timezone.utc),
                codebook_type="x",
                severity="extreme",
            )


class TestSource:
    def test_creation(self):
        s = Source(url="https://example.com", name="Example")
        assert s.credibility_score == 0.5


class TestLocation:
    def test_creation(self):
        loc = Location(name="Jiuquan", country="China", lat=40.96, lon=100.17)
        assert loc.name == "Jiuquan"

    def test_optional_coords(self):
        loc = Location(name="Unknown Place", country="Unknown")
        assert loc.lat is None
        assert loc.lon is None
