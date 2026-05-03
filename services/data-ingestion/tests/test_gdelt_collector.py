"""Tests for gdelt_collector error-handling behavior."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from feeds.gdelt_collector import GDELTCollector
from pipeline import ExtractionConfigError, ExtractionTransientError
from qdrant_client.models import (
    CollectionConfig,
    CollectionInfo,
    CollectionParams,
    Distance,
    VectorParams,
)


def _gdelt_response(articles: list[dict] | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "articles": articles
        if articles is not None
        else [
            {
                "title": "x",
                "url": "http://e/1",
                "seendate": "20260101T000000Z",
                "domain": "ex.com",
                "language": "English",
            }
        ]
    }
    resp.raise_for_status = MagicMock()
    return resp


@pytest.mark.asyncio
async def test_gdelt_transient_skips_upsert():
    """When process_item raises ExtractionTransientError, item is NOT upserted."""
    qdrant = MagicMock()
    qdrant.retrieve.return_value = []  # not a duplicate

    collector = GDELTCollector.__new__(GDELTCollector)
    collector.qdrant = qdrant
    collector._redis = None
    collector._embed = AsyncMock(return_value=[0.0] * 1024)

    with patch("feeds.gdelt_collector.httpx.AsyncClient") as mock_cls, \
         patch("feeds.gdelt_collector.process_item",
               new=AsyncMock(side_effect=ExtractionTransientError("down"))):
        mc = AsyncMock()
        mc.get.return_value = _gdelt_response()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mc)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        await collector.collect()

    qdrant.upsert.assert_not_called()


@pytest.mark.asyncio
async def test_gdelt_config_skips_upsert():
    """When process_item raises ExtractionConfigError, item is NOT upserted."""
    qdrant = MagicMock()
    qdrant.retrieve.return_value = []

    collector = GDELTCollector.__new__(GDELTCollector)
    collector.qdrant = qdrant
    collector._redis = None
    collector._embed = AsyncMock(return_value=[0.0] * 1024)

    with patch("feeds.gdelt_collector.httpx.AsyncClient") as mock_cls, \
         patch("feeds.gdelt_collector.process_item",
               new=AsyncMock(side_effect=ExtractionConfigError("404"))), \
         patch("feeds.gdelt_collector.log.error") as mock_err:
        mc = AsyncMock()
        mc.get.return_value = _gdelt_response()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mc)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        await collector.collect()

    qdrant.upsert.assert_not_called()
    assert any(c.args[0] == "extraction_skipped_config" for c in mock_err.call_args_list)


# ---------------------------------------------------------------------------
# Schema preflight tests — mirror test_qdrant_preflight_ingestion.py pattern
# ---------------------------------------------------------------------------


def _make_phase1_info() -> CollectionInfo:
    """Dense-only Phase 1 collection info (unnamed vector, 1024 cosine)."""
    params = CollectionParams.model_construct(
        vectors=VectorParams(size=1024, distance=Distance.COSINE),
        sparse_vectors=None,
    )
    config = CollectionConfig.model_construct(params=params)
    return CollectionInfo.model_construct(
        config=config,
        payload_schema={},
        points_count=10,
    )


def test_gdelt_validates_schema_when_collection_exists():
    """GDELTCollector._ensure_collection calls validate_collection_schema when collection exists."""
    coll = MagicMock()
    coll.name = "odin_intel"

    mock_qdrant = MagicMock()
    mock_qdrant.get_collections.return_value.collections = [coll]
    mock_qdrant.get_collection.return_value = _make_phase1_info()

    with patch("feeds.gdelt_collector.QdrantClient", return_value=mock_qdrant), \
         patch("feeds.gdelt_collector.validate_collection_schema") as mock_validate:
        collector = GDELTCollector.__new__(GDELTCollector)
        collector.qdrant = mock_qdrant
        collector._redis = None
        collector._ensure_collection()

    mock_validate.assert_called_once()
    mock_qdrant.upsert.assert_not_called()


def test_gdelt_phase2_refuses_phase1_collection():
    """GDELTCollector._ensure_collection raises QdrantSchemaMismatch on schema mismatch, no write."""
    from qdrant_doctor.schema import QdrantSchemaMismatch

    coll = MagicMock()
    coll.name = "odin_intel"

    mock_qdrant = MagicMock()
    mock_qdrant.get_collections.return_value.collections = [coll]
    mock_qdrant.get_collection.return_value = _make_phase1_info()

    with patch("feeds.gdelt_collector.QdrantClient", return_value=mock_qdrant), \
         patch("feeds.gdelt_collector.validate_collection_schema",
               side_effect=QdrantSchemaMismatch("named dense vector required")):
        collector = GDELTCollector.__new__(GDELTCollector)
        collector.qdrant = mock_qdrant
        collector._redis = None
        with pytest.raises(QdrantSchemaMismatch):
            collector._ensure_collection()

    mock_qdrant.upsert.assert_not_called()
