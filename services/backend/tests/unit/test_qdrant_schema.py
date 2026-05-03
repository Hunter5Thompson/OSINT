"""Tests for the backend Qdrant schema validator + preflight in qdrant_client.

Schema validator tests are a service-local copy of the data-ingestion validator
tests — each service tests its own copy independently.
Preflight tests cover the get_qdrant_client() singleton.
"""

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


def _make_info(*, vectors, sparse_vectors=None, points_count: int = 0) -> CollectionInfo:
    params = CollectionParams.model_construct(vectors=vectors, sparse_vectors=sparse_vectors)
    config = CollectionConfig.model_construct(params=params)
    return CollectionInfo.model_construct(
        config=config,
        payload_schema={},
        points_count=points_count,
    )


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
# Validator tests (mirror of data-ingestion/tests/test_qdrant_schema.py)
# ---------------------------------------------------------------------------


class TestValidatorHappyPath:
    def test_dense_only_valid(self) -> None:
        from app.services.qdrant_schema import validate_collection_schema

        validate_collection_schema(_dense_only(), enable_hybrid=False)

    def test_hybrid_valid(self) -> None:
        from app.services.qdrant_schema import validate_collection_schema

        validate_collection_schema(_hybrid(), enable_hybrid=True)


class TestValidatorFailures:
    def test_wrong_size_raises(self) -> None:
        from app.services.qdrant_schema import QdrantSchemaMismatch, validate_collection_schema

        with pytest.raises(QdrantSchemaMismatch, match="768"):
            validate_collection_schema(_dense_only(size=768), enable_hybrid=False)

    def test_wrong_distance_raises(self) -> None:
        from app.services.qdrant_schema import QdrantSchemaMismatch, validate_collection_schema

        with pytest.raises(QdrantSchemaMismatch, match="(?i)dot|distance"):
            validate_collection_schema(_dense_only(distance=Distance.DOT), enable_hybrid=False)

    def test_phase1_collection_in_hybrid_mode_raises(self) -> None:
        """Phase-2 refusal: unnamed dense vector must raise when hybrid is enabled."""
        from app.services.qdrant_schema import QdrantSchemaMismatch, validate_collection_schema

        with pytest.raises(QdrantSchemaMismatch, match="(?i)named|hybrid|dense"):
            validate_collection_schema(_dense_only(), enable_hybrid=True)

    def test_hybrid_missing_sparse_raises(self) -> None:
        from app.services.qdrant_schema import QdrantSchemaMismatch, validate_collection_schema

        with pytest.raises(QdrantSchemaMismatch, match="(?i)sparse|bm25"):
            validate_collection_schema(_hybrid(include_sparse=False), enable_hybrid=True)

    def test_hybrid_missing_named_dense_raises(self) -> None:
        """Hybrid collection without named 'dense' vector must raise."""
        from app.services.qdrant_schema import QdrantSchemaMismatch, validate_collection_schema

        # Named vectors, but NOT named 'dense'
        info = _make_info(
            vectors={"text": VectorParams(size=1024, distance=Distance.COSINE)},
            sparse_vectors={"bm25": SparseVectorParams(index=SparseIndexParams(on_disk=False))},
        )
        with pytest.raises(QdrantSchemaMismatch, match="(?i)dense"):
            validate_collection_schema(info, enable_hybrid=True)

    def test_exception_is_value_error(self) -> None:
        from app.services.qdrant_schema import QdrantSchemaMismatch

        assert issubclass(QdrantSchemaMismatch, ValueError)


# ---------------------------------------------------------------------------
# Preflight integration: get_qdrant_client() validates schema on first call
# ---------------------------------------------------------------------------


class TestQdrantClientPreflight:
    @pytest.mark.asyncio
    async def test_valid_schema_returns_client(self) -> None:
        """Valid dense-only schema → client returned, no exception."""
        import app.services.qdrant_client as qc

        qc._client = None
        qc._schema_validated = False

        mock_client = AsyncMock()
        coll = MagicMock()
        coll.name = "odin_intel"
        mock_client.get_collections.return_value.collections = [coll]
        mock_client.get_collection.return_value = _dense_only()

        with patch("app.services.qdrant_client.AsyncQdrantClient", return_value=mock_client):
            client = await qc.get_qdrant_client()

        assert client is mock_client
        assert qc._schema_validated is True

    @pytest.mark.asyncio
    async def test_schema_validated_only_once(self) -> None:
        """get_collection called only on first get_qdrant_client call."""
        import app.services.qdrant_client as qc

        qc._client = None
        qc._schema_validated = False

        mock_client = AsyncMock()
        coll = MagicMock()
        coll.name = "odin_intel"
        mock_client.get_collections.return_value.collections = [coll]
        mock_client.get_collection.return_value = _dense_only()

        with patch("app.services.qdrant_client.AsyncQdrantClient", return_value=mock_client):
            await qc.get_qdrant_client()
            await qc.get_qdrant_client()  # second call — must NOT re-validate

        assert mock_client.get_collection.call_count == 1

    @pytest.mark.asyncio
    async def test_schema_mismatch_raises_before_any_search(self) -> None:
        """Phase-2 refusal: Phase 1 collection + hybrid mode → raises before client returned."""
        import app.services.qdrant_client as qc
        from app.services.qdrant_schema import QdrantSchemaMismatch

        qc._client = None
        qc._schema_validated = False

        mock_client = AsyncMock()
        coll = MagicMock()
        coll.name = "odin_intel"
        mock_client.get_collections.return_value.collections = [coll]
        # Phase 1 collection schema
        mock_client.get_collection.return_value = _dense_only()

        with (
            patch("app.services.qdrant_client.AsyncQdrantClient", return_value=mock_client),
            patch("app.services.qdrant_client.settings") as mock_settings,
        ):
            mock_settings.qdrant_url = "http://localhost:6333"
            mock_settings.qdrant_collection = "odin_intel"
            mock_settings.enable_hybrid = True  # hybrid mode enabled

            with pytest.raises(QdrantSchemaMismatch):
                await qc.get_qdrant_client()

    @pytest.mark.asyncio
    async def test_absent_collection_does_not_raise(self) -> None:
        """If collection doesn't exist yet, preflight skips validation (let caller handle 404)."""
        import app.services.qdrant_client as qc

        qc._client = None
        qc._schema_validated = False

        mock_client = AsyncMock()
        # No collections returned
        mock_client.get_collections.return_value.collections = []

        with patch("app.services.qdrant_client.AsyncQdrantClient", return_value=mock_client):
            client = await qc.get_qdrant_client()

        assert client is mock_client
        mock_client.get_collection.assert_not_called()
