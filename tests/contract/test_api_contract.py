"""API contract tests to verify backend endpoints match expected schemas."""

import httpx
import pytest

BASE_URL = "http://localhost:8000/api/v1"


@pytest.fixture
def client() -> httpx.Client:
    return httpx.Client(base_url=BASE_URL, timeout=10.0)


class TestHealthContract:
    def test_health_returns_status(self, client: httpx.Client) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert data["status"] == "ok"

    def test_config_returns_cesium_token(self, client: httpx.Client) -> None:
        resp = client.get("/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "cesium_ion_token" in data
        # Must NOT contain secret keys
        assert "opensky_pass" not in data
        assert "aisstream_api_key" not in data


class TestFlightsContract:
    def test_flights_returns_list(self, client: httpx.Client) -> None:
        resp = client.get("/flights")
        assert resp.status_code in (200, 502)  # 502 if upstream down
        if resp.status_code == 200:
            data = resp.json()
            assert isinstance(data, list)
            if len(data) > 0:
                aircraft = data[0]
                assert "icao24" in aircraft
                assert "latitude" in aircraft
                assert "longitude" in aircraft


class TestEarthquakesContract:
    def test_earthquakes_returns_list(self, client: httpx.Client) -> None:
        resp = client.get("/earthquakes")
        assert resp.status_code in (200, 502)
        if resp.status_code == 200:
            data = resp.json()
            assert isinstance(data, list)
            if len(data) > 0:
                quake = data[0]
                assert "magnitude" in quake
                assert "latitude" in quake
                assert "longitude" in quake


class TestSatellitesContract:
    def test_satellites_returns_list(self, client: httpx.Client) -> None:
        resp = client.get("/satellites")
        assert resp.status_code in (200, 502)
        if resp.status_code == 200:
            data = resp.json()
            assert isinstance(data, list)


class TestHotspotsContract:
    def test_hotspots_returns_list(self, client: httpx.Client) -> None:
        resp = client.get("/hotspots")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        if len(data) > 0:
            hotspot = data[0]
            assert "id" in hotspot
            assert "name" in hotspot
            assert "threat_level" in hotspot
            assert hotspot["threat_level"] in (
                "CRITICAL",
                "HIGH",
                "ELEVATED",
                "MODERATE",
            )
