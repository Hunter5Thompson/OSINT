"""TDD tests for preflight schema validation in the data-ingestion writer.

Tests prove that validate_collection_schema is called inside _ensure_collection
BEFORE any Qdrant write/upsert operation, and that a schema mismatch raises
QdrantSchemaMismatch without performing a write.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from qdrant_client.models import (
    CollectionConfig,
    CollectionInfo,
    CollectionParams,
    Distance,
    VectorParams,
)


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


def _make_mock_settings(*, enable_hybrid: bool = False):
    s = MagicMock()
    s.qdrant_url = "http://localhost:6333"
    s.qdrant_collection = "odin_intel"
    s.tei_embed_url = "http://localhost:8001"
    s.http_timeout = 30.0
    s.embedding_dimensions = 1024
    s.enable_hybrid = enable_hybrid
    return s


class TestBaseCollectorPreflight:
    """BaseCollector._ensure_collection validates schema when collection exists."""

    @pytest.mark.asyncio
    async def test_valid_schema_does_not_raise(self):
        """Existing Phase 1 collection + dense-only mode → no raise."""
        from feeds.base import BaseCollector

        class ConcreteCollector(BaseCollector):
            async def collect(self) -> None:
                pass

        mock_settings = _make_mock_settings(enable_hybrid=False)
        phase1_info = _make_phase1_info()

        coll = MagicMock()
        coll.name = "odin_intel"

        mock_qdrant = MagicMock()
        mock_qdrant.get_collections.return_value.collections = [coll]
        mock_qdrant.get_collection.return_value = phase1_info

        with patch("feeds.base.QdrantClient", return_value=mock_qdrant):
            collector = ConcreteCollector(settings=mock_settings)

        # Should complete without raising
        await collector._ensure_collection()
        # get_collection must have been called to inspect schema
        mock_qdrant.get_collection.assert_called_once_with("odin_intel")

    @pytest.mark.asyncio
    async def test_phase2_code_refuses_phase1_collection_before_write(self):
        """Phase 2 hybrid code must refuse Phase 1 collection before any upsert.

        This is the key Phase-2 refusal test: when enable_hybrid=True and the
        existing collection has the Phase 1 schema (unnamed dense, no sparse),
        _ensure_collection must raise QdrantSchemaMismatch without calling
        qdrant.upsert.
        """
        from feeds.base import BaseCollector
        from qdrant_doctor.schema import QdrantSchemaMismatch

        class ConcreteCollector(BaseCollector):
            async def collect(self) -> None:
                pass

        mock_settings = _make_mock_settings(enable_hybrid=True)
        phase1_info = _make_phase1_info()

        coll = MagicMock()
        coll.name = "odin_intel"

        mock_qdrant = MagicMock()
        mock_qdrant.get_collections.return_value.collections = [coll]
        mock_qdrant.get_collection.return_value = phase1_info

        with patch("feeds.base.QdrantClient", return_value=mock_qdrant):
            collector = ConcreteCollector(settings=mock_settings)

        with pytest.raises(QdrantSchemaMismatch):
            await collector._ensure_collection()

        # Absolutely no upsert must have been attempted
        mock_qdrant.upsert.assert_not_called()

    @pytest.mark.asyncio
    async def test_schema_check_skipped_on_second_call_when_ready(self):
        """_ensure_collection skips validation when _collection_ready is already True."""
        from feeds.base import BaseCollector

        class ConcreteCollector(BaseCollector):
            async def collect(self) -> None:
                pass

        mock_settings = _make_mock_settings(enable_hybrid=False)

        mock_qdrant = MagicMock()
        with patch("feeds.base.QdrantClient", return_value=mock_qdrant):
            collector = ConcreteCollector(settings=mock_settings)

        collector._collection_ready = True
        await collector._ensure_collection()

        # Neither get_collections nor get_collection called on second run
        mock_qdrant.get_collections.assert_not_called()
        mock_qdrant.get_collection.assert_not_called()

    @pytest.mark.asyncio
    async def test_wrong_vector_size_raises_before_write(self):
        """Collection with wrong vector size must raise before any write."""
        from feeds.base import BaseCollector
        from qdrant_doctor.schema import QdrantSchemaMismatch

        class ConcreteCollector(BaseCollector):
            async def collect(self) -> None:
                pass

        mock_settings = _make_mock_settings(enable_hybrid=False)

        # Wrong size: 768 instead of 1024
        params = CollectionParams.model_construct(
            vectors=VectorParams(size=768, distance=Distance.COSINE),
            sparse_vectors=None,
        )
        config = CollectionConfig.model_construct(params=params)
        bad_info = CollectionInfo.model_construct(
            config=config,
            payload_schema={},
            points_count=5,
        )

        coll = MagicMock()
        coll.name = "odin_intel"
        mock_qdrant = MagicMock()
        mock_qdrant.get_collections.return_value.collections = [coll]
        mock_qdrant.get_collection.return_value = bad_info

        with patch("feeds.base.QdrantClient", return_value=mock_qdrant):
            collector = ConcreteCollector(settings=mock_settings)

        with pytest.raises(QdrantSchemaMismatch, match="768"):
            await collector._ensure_collection()

        mock_qdrant.upsert.assert_not_called()
