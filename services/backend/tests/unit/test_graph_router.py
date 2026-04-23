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

    def test_network_ignores_rows_with_missing_source_or_target(self, client):
        with patch("app.routers.graph._read_query", new_callable=AsyncMock) as mock:
            mock.return_value = [
                {"source": None, "relationship": "INVOLVES", "target": "EU", "target_type": "Entity", "target_subtype": "organization"},
                {"source": "NATO", "relationship": "INVOLVES", "target": None, "target_type": "Entity", "target_subtype": "organization"},
                {"source": "NATO", "relationship": "INVOLVES", "target": "EU", "target_type": "Entity", "target_subtype": "organization"},
            ]
            resp = client.get("/api/v1/graph/network/NATO")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["edges"]) == 1
            assert data["edges"][0]["source"] == "NATO"
            assert data["edges"][0]["target"] == "EU"

    def test_network_keeps_root_node_when_no_edges(self, client):
        with patch("app.routers.graph._read_query", new_callable=AsyncMock) as mock:
            mock.return_value = []
            resp = client.get("/api/v1/graph/network/NATO")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["nodes"]) == 1
            assert data["nodes"][0]["id"] == "NATO"
            assert data["edges"] == []

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

    def test_search_with_missing_id_falls_back_to_name(self, client):
        with patch("app.routers.graph._read_query", new_callable=AsyncMock) as mock:
            mock.return_value = [{"name": "Iran", "type": "location", "id": None}]
            resp = client.get("/api/v1/graph/search?q=ir&limit=10")
            assert resp.status_code == 200
            data = resp.json()
            assert data["nodes"][0]["id"] == "Iran"

    def test_search_query_uses_element_id_not_e_id(self, client):
        with patch("app.routers.graph._read_query", new_callable=AsyncMock) as mock:
            mock.return_value = []
            resp = client.get("/api/v1/graph/search?q=ir&limit=10")
            assert resp.status_code == 200
            cypher = mock.call_args.args[0]
            assert "elementId(e) AS id" in cypher
            assert "e.id AS id" not in cypher

    def test_events_endpoint(self, client):
        with patch("app.routers.graph._read_query", new_callable=AsyncMock) as mock:
            mock.return_value = [
                {"id": "ev-1", "name": "Missile Test", "type": "military.weapons_test", "severity": "high", "timestamp": "2026-03-30"},
            ]
            resp = client.get("/api/v1/graph/events?entity=NorthKorea")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["nodes"]) == 1

    def test_events_query_uses_element_id_not_ev_id(self, client):
        with patch("app.routers.graph._read_query", new_callable=AsyncMock) as mock:
            mock.return_value = []
            resp = client.get("/api/v1/graph/events")
            assert resp.status_code == 200
            cypher = mock.call_args.args[0]
            assert "elementId(ev) AS id" in cypher
            assert "ev.id AS id" not in cypher


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

    def test_codebook_type_filter(self, client):
        with patch("app.routers.graph._read_query", new_callable=AsyncMock) as mock:
            mock.return_value = [
                {
                    "id": "ev-4", "title": "Airstrike",
                    "codebook_type": "military.airstrike",
                    "severity": "critical", "timestamp": "2026-03-30T06:00:00",
                    "location_name": "Aleppo", "country": "Syria",
                    "lat": 36.20, "lon": 37.16,
                },
            ]
            resp = client.get("/api/v1/graph/events/geo?codebook_type=military")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["events"]) == 1
            # Verify Cypher contains STARTS WITH filter
            call_args = mock.call_args
            cypher = call_args.args[0]
            assert "STARTS WITH" in cypher
            assert call_args.args[1]["codebook_type"] == "military"

    def test_geo_events_query_uses_element_id_not_ev_id(self, client):
        with patch("app.routers.graph._read_query", new_callable=AsyncMock) as mock:
            mock.return_value = []
            resp = client.get("/api/v1/graph/events/geo")
            assert resp.status_code == 200
            cypher = mock.call_args.args[0]
            assert "elementId(ev) AS id" in cypher
            assert "ev.id AS id" not in cypher


class TestConfigEndpoint:
    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_config_includes_events_in_default_layers(self, client):
        resp = client.get("/api/v1/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "events" in data["default_layers"]
        assert data["default_layers"]["events"] is False
