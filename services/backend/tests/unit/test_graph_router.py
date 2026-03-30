"""Tests for graph router endpoints with mocked Neo4j."""

import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from app.main import app


class TestGraphEndpoints:
    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_entity_not_found(self, client):
        with patch("app.routers.graph._read_query", new_callable=AsyncMock) as mock:
            mock.return_value = []
            resp = client.get("/api/v1/graph/entity/NonExistent")
            assert resp.status_code == 200
            data = resp.json()
            assert data["nodes"] == []

    def test_entity_found(self, client):
        with patch("app.routers.graph._read_query", new_callable=AsyncMock) as mock:
            mock.return_value = [
                {"name": "NATO", "type": "organization", "id": "e-1", "aliases": [], "confidence": 0.9}
            ]
            resp = client.get("/api/v1/graph/entity/NATO")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["nodes"]) == 1
            assert data["nodes"][0]["name"] == "NATO"

    def test_neighbors_returns_edges(self, client):
        with patch("app.routers.graph._read_query", new_callable=AsyncMock) as mock:
            mock.return_value = [
                {"source": "NATO", "relationship": "INVOLVES", "target": "EU", "target_type": "Entity", "target_subtype": "organization"},
            ]
            resp = client.get("/api/v1/graph/neighbors/NATO")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["edges"]) >= 1

    def test_search_returns_matching(self, client):
        with patch("app.routers.graph._read_query", new_callable=AsyncMock) as mock:
            mock.return_value = [
                {"name": "NATO", "type": "organization", "id": "e-1"},
                {"name": "National Guard", "type": "military_unit", "id": "e-2"},
            ]
            resp = client.get("/api/v1/graph/search?q=nat&limit=10")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["nodes"]) == 2

    def test_events_endpoint(self, client):
        with patch("app.routers.graph._read_query", new_callable=AsyncMock) as mock:
            mock.return_value = [
                {"id": "ev-1", "name": "Missile Test", "type": "military.weapons_test", "severity": "high", "timestamp": "2026-03-30"},
            ]
            resp = client.get("/api/v1/graph/events?entity=NorthKorea")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["nodes"]) == 1


class TestGeoEventsEndpoint:
    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_returns_events_with_location(self, client):
        with patch("app.routers.graph._read_query", new_callable=AsyncMock) as mock:
            mock.return_value = [
                {
                    "id": "ev-1", "title": "Satellite Launch",
                    "codebook_type": "space.satellite_launch",
                    "severity": "medium", "timestamp": "2026-03-30T10:00:00",
                    "location_name": "Jiuquan", "country": "China",
                    "lat": 40.96, "lon": 100.28,
                },
            ]
            resp = client.get("/api/v1/graph/events/geo")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["events"]) == 1
            assert data["events"][0]["lat"] == 40.96
            assert data["events"][0]["title"] == "Satellite Launch"

    def test_returns_events_without_location(self, client):
        with patch("app.routers.graph._read_query", new_callable=AsyncMock) as mock:
            mock.return_value = [
                {
                    "id": "ev-2", "title": "Cyber Attack",
                    "codebook_type": "cyber.ransomware_attack",
                    "severity": "high", "timestamp": "2026-03-30T12:00:00",
                    "location_name": None, "country": None,
                    "lat": None, "lon": None,
                },
            ]
            resp = client.get("/api/v1/graph/events/geo")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["events"]) == 1
            assert data["events"][0]["lat"] is None

    def test_entity_filter(self, client):
        with patch("app.routers.graph._read_query", new_callable=AsyncMock) as mock:
            mock.return_value = [
                {
                    "id": "ev-3", "title": "Missile Test",
                    "codebook_type": "military.weapons_test",
                    "severity": "critical", "timestamp": "2026-03-30T08:00:00",
                    "location_name": "Pyongyang", "country": "North Korea",
                    "lat": 39.03, "lon": 125.75,
                },
            ]
            resp = client.get("/api/v1/graph/events/geo?entity=DPRK")
            assert resp.status_code == 200
            call_args = mock.call_args
            assert "$entity" in call_args.args[0] or "entity" in str(call_args)
