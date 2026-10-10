"""The real legacy writer/reader pair must preserve publication vs point-write time."""
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import httpx

import rag.indexer as indexer
from rag.evidence import to_evidence_item


def test_existing_payload_publication_field_survives_the_legacy_rss_reader():
    payload = indexer.build_document_payload(
        title="synthetic", content="synthetic", source="rss", region=None, hotspot_ids=None,
        published_at="2020-01-02T00:00:00Z", chunk_index=0, total_chunks=1,
    )
    item = to_evidence_item(payload)
    assert item.source.published_at == datetime(2020, 1, 2, tzinfo=UTC)
    assert item.ingested_at is None


async def test_future_upsert_stamps_ingestion_without_overwriting_publication(monkeypatch):
    points = []

    def capture(request):
        points.extend(json.loads(request.content)["points"])
        return httpx.Response(200, json={"status": "ok"})

    client = httpx.AsyncClient
    monkeypatch.setattr(indexer, "ensure_collection", AsyncMock())
    monkeypatch.setattr(indexer, "embed_text", AsyncMock(return_value=[0.1] * 1024))
    monkeypatch.setattr(indexer.httpx, "AsyncClient", lambda **kwargs: client(
        transport=httpx.MockTransport(capture), **kwargs,
    ))
    before = datetime.now(UTC)
    assert await indexer.ingest_document(
        "synthetic", "synthetic document", "rss", published_at="2020-01-02T00:00:00Z",
    ) == 1
    after = datetime.now(UTC)
    payload = points[0]["payload"]
    item = to_evidence_item(payload)
    assert item.source.published_at == datetime(2020, 1, 2, tzinfo=UTC)
    assert item.ingested_at is not None and before <= item.ingested_at <= after
    assert payload["ingested_epoch"] == item.ingested_at.timestamp()
