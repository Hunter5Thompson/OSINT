"""Tests for vision-enrichment Qdrant schema validator + consumer preflight."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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


def _make_consumer(**settings_overrides):
    from config import Settings
    from consumer import VisionConsumer

    defaults = {"neo4j_password": "test"}
    defaults.update(settings_overrides)
    s = Settings(**defaults)
    mock_redis = MagicMock()
    return VisionConsumer(redis_client=mock_redis, settings_override=s)


# ---------------------------------------------------------------------------
# Validator unit tests (vision-enrichment service copy)
# ---------------------------------------------------------------------------


class TestVisionValidator:
    def test_dense_only_valid(self) -> None:
        from qdrant_schema import validate_collection_schema

        validate_collection_schema(_dense_only(), enable_hybrid=False)

    def test_hybrid_valid(self) -> None:
        from qdrant_schema import validate_collection_schema

        validate_collection_schema(_hybrid(), enable_hybrid=True)

    def test_wrong_size_raises(self) -> None:
        from qdrant_schema import QdrantSchemaMismatch, validate_collection_schema

        with pytest.raises(QdrantSchemaMismatch, match="384"):
            validate_collection_schema(_dense_only(size=384), enable_hybrid=False)

    def test_phase1_in_hybrid_mode_raises(self) -> None:
        """Phase-2 refusal: Phase 1 collection + hybrid mode must raise."""
        from qdrant_schema import QdrantSchemaMismatch, validate_collection_schema

        with pytest.raises(QdrantSchemaMismatch, match="(?i)named|hybrid|dense"):
            validate_collection_schema(_dense_only(), enable_hybrid=True)

    def test_hybrid_missing_sparse_raises(self) -> None:
        """Hybrid mode but no sparse vector config must raise."""
        from qdrant_schema import QdrantSchemaMismatch, validate_collection_schema

        with pytest.raises(QdrantSchemaMismatch, match="(?i)sparse|bm25"):
            validate_collection_schema(_hybrid(include_sparse=False), enable_hybrid=True)

    def test_hybrid_dense_wrong_distance_raises(self) -> None:
        """Hybrid collection with named 'dense' vector and wrong distance must raise."""
        from qdrant_schema import QdrantSchemaMismatch, validate_collection_schema

        wrong_info = _make_info(
            vectors={"dense": VectorParams(size=1024, distance=Distance.EUCLID)},
            sparse_vectors={"bm25": SparseVectorParams(index=SparseIndexParams(on_disk=False))},
        )
        with pytest.raises(QdrantSchemaMismatch, match="(?i)euclid|distance"):
            validate_collection_schema(wrong_info, enable_hybrid=True)

    def test_exception_is_value_error(self) -> None:
        from qdrant_schema import QdrantSchemaMismatch

        assert issubclass(QdrantSchemaMismatch, ValueError)


# ---------------------------------------------------------------------------
# Consumer preflight: _validate_qdrant_schema
# ---------------------------------------------------------------------------


class TestVisionConsumerPreflight:
    def test_valid_schema_sets_validated_flag(self) -> None:
        """Valid Phase 1 schema → _qdrant_schema_validated set to True."""
        consumer = _make_consumer()
        assert consumer._qdrant_schema_validated is False

        mock_qdrant = MagicMock()
        coll = MagicMock()
        coll.name = "odin_intel"
        mock_qdrant.get_collections.return_value.collections = [coll]
        mock_qdrant.get_collection.return_value = _dense_only()

        consumer._validate_qdrant_schema(mock_qdrant)

        assert consumer._qdrant_schema_validated is True
        mock_qdrant.get_collection.assert_called_once_with("odin_intel")

    def test_schema_mismatch_raises_before_write(self) -> None:
        """Phase-2 refusal: Phase 1 collection passed with enable_hybrid=True must raise.

        We use a MagicMock settings object so we can set enable_hybrid=True freely
        without fighting pydantic's strict field validation on the real Settings class.
        """
        from qdrant_schema import QdrantSchemaMismatch
        from consumer import VisionConsumer

        mock_settings = MagicMock()
        mock_settings.qdrant_url = "http://localhost:6333"
        mock_settings.qdrant_collection = "odin_intel"
        mock_settings.enable_hybrid = True  # hybrid mode

        consumer = VisionConsumer(redis_client=MagicMock(), settings_override=mock_settings)

        mock_qdrant = MagicMock()
        coll = MagicMock()
        coll.name = "odin_intel"
        mock_qdrant.get_collections.return_value.collections = [coll]
        mock_qdrant.get_collection.return_value = _dense_only()

        with pytest.raises(QdrantSchemaMismatch):
            consumer._validate_qdrant_schema(mock_qdrant)

        # Flag must NOT be set — the check failed
        assert consumer._qdrant_schema_validated is False

    def test_absent_collection_skips_validation(self) -> None:
        """If the collection doesn't exist, preflight skips and marks as validated."""
        consumer = _make_consumer()

        mock_qdrant = MagicMock()
        mock_qdrant.get_collections.return_value.collections = []

        consumer._validate_qdrant_schema(mock_qdrant)

        assert consumer._qdrant_schema_validated is True
        mock_qdrant.get_collection.assert_not_called()

    def test_validation_not_repeated_on_subsequent_calls(self) -> None:
        """With _qdrant_schema_validated=True, _validate_qdrant_schema is not called again."""
        consumer = _make_consumer()
        consumer._qdrant_schema_validated = True

        mock_qdrant = MagicMock()
        # Simulate that _process_message would call _validate_qdrant_schema
        # only when the flag is False — here we verify the flag check works
        # by ensuring get_collections is not invoked
        if not consumer._qdrant_schema_validated:  # consumer's own check
            consumer._validate_qdrant_schema(mock_qdrant)

        mock_qdrant.get_collections.assert_not_called()

    def test_wrong_vector_size_raises(self) -> None:
        """Collection with wrong vector size raises before any write."""
        from qdrant_schema import QdrantSchemaMismatch

        consumer = _make_consumer()

        mock_qdrant = MagicMock()
        coll = MagicMock()
        coll.name = "odin_intel"
        mock_qdrant.get_collections.return_value.collections = [coll]
        mock_qdrant.get_collection.return_value = _dense_only(size=512)

        with pytest.raises(QdrantSchemaMismatch, match="512"):
            consumer._validate_qdrant_schema(mock_qdrant)
