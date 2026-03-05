"""Integration tests for health and config endpoints."""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


class TestHealthEndpoint:
    def test_health_returns_ok(self, client: TestClient) -> None:
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "timestamp" in data
        assert "version" in data

    def test_config_returns_token(self, client: TestClient) -> None:
        resp = client.get("/api/v1/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "cesium_ion_token" in data
        assert "default_layers" in data
        # Verify no secret keys are leaked
        assert "opensky_pass" not in str(data)
        assert "aisstream_api_key" not in str(data)
