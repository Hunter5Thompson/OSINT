import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.main import app


def test_readiness_separates_required_dependencies_from_optional_cache(monkeypatch):
    from app.routers import readiness

    monkeypatch.setattr(readiness, "read_query", AsyncMock(return_value=[{"ready": 1}]))
    qdrant = AsyncMock()
    monkeypatch.setattr(readiness, "get_qdrant_client", AsyncMock(return_value=qdrant))
    monkeypatch.setattr(readiness, "validate_collection_schema", lambda *a, **k: None)
    cache = AsyncMock()
    cache.check_ready.return_value = True
    app.state.cache = cache
    client = TestClient(app)
    assert client.get("/api/health/ready").json()["status"] == "ready"
    cache.check_ready.return_value = False
    response = client.get("/api/health/ready")
    assert response.status_code == 200 and response.json()["status"] == "degraded"
    qdrant.get_collection.side_effect = ConnectionError("private address")
    response = client.get("/api/health/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
    assert "private address" not in response.text
    assert client.get("/api/health").status_code == 200


async def test_dependency_probes_timeout_without_blocking_readiness(monkeypatch):
    from app.routers import readiness

    async def never():
        await asyncio.sleep(10)

    monkeypatch.setattr(readiness, "PROBE_TIMEOUT_S", 0.01)
    monkeypatch.setattr(readiness, "check_neo4j", never)
    monkeypatch.setattr(readiness, "check_qdrant", never)
    cache = SimpleNamespace(check_ready=never)
    result = await asyncio.wait_for(readiness.readiness_report(cache), timeout=0.2)
    assert result.status == "unavailable"
