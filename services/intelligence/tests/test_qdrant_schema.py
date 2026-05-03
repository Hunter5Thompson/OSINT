"""Tests for intelligence service Qdrant schema validator + retriever preflight."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from qdrant_client.models import (
    CollectionConfig,
    CollectionInfo,
    CollectionParams,
    Distance,
    SparseIndexParams,
    SparseVectorParams,
    VectorParams,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_info(*, vectors, sparse_vectors=None) -> CollectionInfo:
    params = CollectionParams.model_construct(vectors=vectors, sparse_vectors=sparse_vectors)
    config = CollectionConfig.model_construct(params=params)
    return CollectionInfo.model_construct(config=config, payload_schema={}, points_count=0)


def _dense_only(size: int = 1024, distance: Distance = Distance.COSINE) -> CollectionInfo:
    return _make_info(vectors=VectorParams(size=size, distance=distance))


def _hybrid(include_sparse: bool = True) -> CollectionInfo:
    vectors = {"dense": VectorParams(size=1024, distance=Distance.COSINE)}
    sparse = (
        {"bm25": SparseVectorParams(index=SparseIndexParams(on_disk=False))}
        if include_sparse
        else None
    )
    return _make_info(vectors=vectors, sparse_vectors=sparse)


# ---------------------------------------------------------------------------
# Validator unit tests (intelligence service copy)
# ---------------------------------------------------------------------------


class TestIntelligenceValidator:
    def test_dense_only_valid(self) -> None:
        from rag.qdrant_schema import validate_collection_schema

        validate_collection_schema(_dense_only(), enable_hybrid=False)

    def test_hybrid_valid(self) -> None:
        from rag.qdrant_schema import validate_collection_schema

        validate_collection_schema(_hybrid(), enable_hybrid=True)

    def test_wrong_size_raises(self) -> None:
        from rag.qdrant_schema import QdrantSchemaMismatch, validate_collection_schema

        with pytest.raises(QdrantSchemaMismatch, match="768"):
            validate_collection_schema(_dense_only(size=768), enable_hybrid=False)

    def test_phase1_in_hybrid_mode_raises(self) -> None:
        """Phase-2 refusal: Phase 1 collection + hybrid mode must raise."""
        from rag.qdrant_schema import QdrantSchemaMismatch, validate_collection_schema

        with pytest.raises(QdrantSchemaMismatch, match="(?i)named|hybrid|dense"):
            validate_collection_schema(_dense_only(), enable_hybrid=True)

    def test_hybrid_missing_sparse_raises(self) -> None:
        from rag.qdrant_schema import QdrantSchemaMismatch, validate_collection_schema

        with pytest.raises(QdrantSchemaMismatch, match="(?i)sparse"):
            validate_collection_schema(_hybrid(include_sparse=False), enable_hybrid=True)

    def test_exception_is_value_error(self) -> None:
        from rag.qdrant_schema import QdrantSchemaMismatch

        assert issubclass(QdrantSchemaMismatch, ValueError)


# ---------------------------------------------------------------------------
# Preflight integration: retriever._ensure_schema_validated
# ---------------------------------------------------------------------------


class TestRetrieverPreflight:
    @pytest.mark.asyncio
    async def test_valid_schema_no_raise(self) -> None:
        """Valid Phase 1 schema + dense-only mode → no exception."""
        import rag.retriever as retriever

        retriever._schema_validated = False

        mock_client = AsyncMock()
        coll = MagicMock()
        coll.name = "odin_intel"
        mock_client.get_collections.return_value.collections = [coll]
        mock_client.get_collection.return_value = _dense_only()

        with (
            patch("rag.retriever.AsyncQdrantClient", return_value=mock_client),
            patch("rag.retriever.settings") as mock_settings,
        ):
            mock_settings.qdrant_url = "http://localhost:6333"
            mock_settings.qdrant_collection = "odin_intel"
            mock_settings.enable_hybrid = False

            await retriever._ensure_schema_validated()

        assert retriever._schema_validated is True

    @pytest.mark.asyncio
    async def test_phase2_code_refuses_phase1_collection(self) -> None:
        """Phase 2 hybrid mode + Phase 1 collection schema → raises QdrantSchemaMismatch.

        This is the Phase-2 refusal test: search() must NOT reach Qdrant when
        the schema doesn't match the configured mode.
        """
        import rag.retriever as retriever
        from rag.qdrant_schema import QdrantSchemaMismatch

        retriever._schema_validated = False

        mock_client = AsyncMock()
        coll = MagicMock()
        coll.name = "odin_intel"
        mock_client.get_collections.return_value.collections = [coll]
        mock_client.get_collection.return_value = _dense_only()  # Phase 1 schema

        with (
            patch("rag.retriever.AsyncQdrantClient", return_value=mock_client),
            patch("rag.retriever.settings") as mock_settings,
        ):
            mock_settings.qdrant_url = "http://localhost:6333"
            mock_settings.qdrant_collection = "odin_intel"
            mock_settings.enable_hybrid = True  # hybrid enabled

            with pytest.raises(QdrantSchemaMismatch):
                await retriever._ensure_schema_validated()

    @pytest.mark.asyncio
    async def test_schema_validated_only_once(self) -> None:
        """get_collection called only once across multiple _ensure_schema_validated calls."""
        import rag.retriever as retriever

        retriever._schema_validated = False

        mock_client = AsyncMock()
        coll = MagicMock()
        coll.name = "odin_intel"
        mock_client.get_collections.return_value.collections = [coll]
        mock_client.get_collection.return_value = _dense_only()

        with (
            patch("rag.retriever.AsyncQdrantClient", return_value=mock_client),
            patch("rag.retriever.settings") as mock_settings,
        ):
            mock_settings.qdrant_url = "http://localhost:6333"
            mock_settings.qdrant_collection = "odin_intel"
            mock_settings.enable_hybrid = False

            await retriever._ensure_schema_validated()
            await retriever._ensure_schema_validated()

        assert mock_client.get_collection.call_count == 1

    @pytest.mark.asyncio
    async def test_absent_collection_skips_validation(self) -> None:
        """If collection doesn't exist yet, preflight skips (no raise)."""
        import rag.retriever as retriever

        retriever._schema_validated = False

        mock_client = AsyncMock()
        mock_client.get_collections.return_value.collections = []

        with (
            patch("rag.retriever.AsyncQdrantClient", return_value=mock_client),
            patch("rag.retriever.settings") as mock_settings,
        ):
            mock_settings.qdrant_url = "http://localhost:6333"
            mock_settings.qdrant_collection = "odin_intel"
            mock_settings.enable_hybrid = False

            await retriever._ensure_schema_validated()

        mock_client.get_collection.assert_not_called()
        assert retriever._schema_validated is True
