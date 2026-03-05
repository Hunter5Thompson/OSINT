"""Unit tests for Pydantic models."""

from datetime import datetime, timezone

from app.models.earthquake import Earthquake
from app.models.flight import Aircraft
from app.models.hotspot import Hotspot
from app.models.satellite import Satellite
from app.models.vessel import Vessel


class TestAircraftModel:
    def test_minimal_aircraft(self) -> None:
        a = Aircraft(icao24="abc123", latitude=51.5, longitude=-0.1)
        assert a.icao24 == "abc123"
        assert a.is_military is False
        assert a.on_ground is False

    def test_full_aircraft(self) -> None:
        a = Aircraft(
            icao24="abc123",
            callsign="DLH123",
            latitude=51.5,
            longitude=-0.1,
            altitude_m=10000,
            velocity_ms=250,
            heading=90,
            vertical_rate=5.0,
            on_ground=False,
            is_military=True,
            aircraft_type="A320",
        )
        assert a.callsign == "DLH123"
        assert a.is_military is True


class TestSatelliteModel:
    def test_satellite(self) -> None:
        s = Satellite(
            norad_id=25544,
            name="ISS (ZARYA)",
            tle_line1="1 25544U ...",
            tle_line2="2 25544 ...",
            category="station",
            inclination_deg=51.64,
            period_min=92.87,
        )
        assert s.norad_id == 25544
        assert s.category == "station"


class TestEarthquakeModel:
    def test_earthquake(self) -> None:
        e = Earthquake(
            id="us7000abc",
            latitude=35.0,
            longitude=139.0,
            depth_km=10.5,
            magnitude=6.2,
            place="Near Tokyo, Japan",
            time=datetime.now(timezone.utc),
            tsunami=False,
        )
        assert e.magnitude == 6.2
        assert e.tsunami is False


class TestVesselModel:
    def test_vessel(self) -> None:
        v = Vessel(mmsi=123456789, latitude=51.5, longitude=-0.1)
        assert v.mmsi == 123456789
        assert v.speed_knots == 0.0


class TestHotspotModel:
    def test_hotspot(self) -> None:
        h = Hotspot(
            id="ukr-001",
            name="Ukraine",
            latitude=48.3,
            longitude=37.8,
            region="Eastern Europe",
            threat_level="CRITICAL",
            description="Active conflict",
        )
        assert h.threat_level == "CRITICAL"
