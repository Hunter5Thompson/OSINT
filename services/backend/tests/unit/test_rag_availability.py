from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from app.main import app


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_manual_ingest_does_not_claim_a_queued_job():
    response = TestClient(app).post("/api/rag/ingest", json={"content": "synthetic"})
    assert response.status_code == 501


def test_statistics_failure_preserves_unknown_count_and_collections():
    for status, body in [(503, "down"), (200, "not-json"), (200, '{}')]:
        client = _client(lambda request, s=status, b=body: httpx.Response(s, text=b))
        with patch("app.routers.rag._shared_http_client", return_value=client):
            result = TestClient(app).get("/api/rag/stats").json()
        assert result["availability"] == "unavailable"
        assert result["total_documents"] is None
        assert result["collections"] is None


def test_partial_source_count_failure_does_not_become_zero_or_hide_other_counts():
    import json

    def handler(request):
        source = json.loads(request.content)["filter"]["must"][0]["match"]["value"]
        return (httpx.Response(503) if source == "rss"
                else httpx.Response(200, json={"result": {"count": 7}}))

    with patch("app.routers.rag._shared_http_client", return_value=_client(handler)):
        sources = TestClient(app).get("/api/rag/sources").json()
    rss = next(row for row in sources if row["type"] == "rss")
    gdelt = next(row for row in sources if row["type"] == "gdelt_gkg")
    assert rss["availability"] == "unavailable" and rss["doc_count"] is None
    assert gdelt["availability"] == "available" and gdelt["doc_count"] == 7


def test_exact_zero_documents_is_available_not_unknown():
    from app.config import settings

    def handler(request):
        return httpx.Response(200, json={"result": (
            {"collections": [{"name": settings.qdrant_collection}]}
            if request.method == "GET" else {"count": 0}
        )})

    with patch("app.routers.rag._shared_http_client", return_value=_client(handler)):
        result = TestClient(app).get("/api/rag/stats").json()
    assert result["availability"] == "available"
    assert result["total_documents"] == 0
    assert result["collections"] == [settings.qdrant_collection]
