"""TDD tests for the Qdrant schema validator.

Tests cover all failure / pass modes described in the Qdrant SoT Phase 1 plan.
All tests use mocked CollectionInfo — no live Qdrant required.
"""

from __future__ import annotations

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


def _make_collection_info(
    *,
    vectors,
    sparse_vectors=None,
    points_count: int = 0,
) -> CollectionInfo:
    """Build a minimal CollectionInfo using model_construct to bypass validation.

    model_construct skips pydantic field validators so we can build the nested
    structure without filling out every required sub-field (HnswConfig, etc.).
    """
    params = CollectionParams.model_construct(vectors=vectors, sparse_vectors=sparse_vectors)
    config = CollectionConfig.model_construct(params=params)
    return CollectionInfo.model_construct(
        config=config,
        payload_schema={},
        points_count=points_count,
    )


def _dense_only_collection(size: int = 1024, distance: Distance = Distance.COSINE):
    """Phase 1 schema: single unnamed dense vector."""
    return _make_collection_info(vectors=VectorParams(size=size, distance=distance))


def _hybrid_collection(
    dense_size: int = 1024,
    dense_distance: Distance = Distance.COSINE,
    include_sparse: bool = True,
):
    """Phase 2 schema: named dense + sparse vectors."""
    vectors = {"dense": VectorParams(size=dense_size, distance=dense_distance)}
    sparse = (
        {"bm25": SparseVectorParams(index=SparseIndexParams(on_disk=False))}
        if include_sparse
        else None
    )
    return _make_collection_info(vectors=vectors, sparse_vectors=sparse)


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


class TestDenseOnlyHappyPath:
    """Dense-only mode: unnamed vector, size 1024, cosine — must not raise."""

    def test_valid_dense_only(self):
        from qdrant_doctor.schema import validate_collection_schema

        info = _dense_only_collection()
        # Should not raise
        validate_collection_schema(info, enable_hybrid=False)

    def test_valid_hybrid_collection(self):
        """Hybrid mode with named dense + BM25 sparse — must not raise."""
        from qdrant_doctor.schema import validate_collection_schema

        info = _hybrid_collection()
        validate_collection_schema(info, enable_hybrid=True)


# ---------------------------------------------------------------------------
# Dense-only failure modes
# ---------------------------------------------------------------------------


class TestDenseOnlyFailures:
    def test_wrong_vector_size_raises(self):
        """Dense-only with size != 1024 must raise mentioning the size."""
        from qdrant_doctor.schema import QdrantSchemaMismatch, validate_collection_schema

        info = _dense_only_collection(size=768)
        with pytest.raises(QdrantSchemaMismatch, match="768"):
            validate_collection_schema(info, enable_hybrid=False)

    def test_wrong_distance_raises(self):
        """Dense-only with distance != Cosine must raise mentioning distance."""
        from qdrant_doctor.schema import QdrantSchemaMismatch, validate_collection_schema

        info = _dense_only_collection(distance=Distance.DOT)
        with pytest.raises(QdrantSchemaMismatch, match="(?i)dot|distance"):
            validate_collection_schema(info, enable_hybrid=False)

    def test_named_dense_in_dense_only_mode_raises(self):
        """Hybrid collection (named 'dense') passed to dense-only mode must raise."""
        from qdrant_doctor.schema import QdrantSchemaMismatch, validate_collection_schema

        info = _hybrid_collection()
        with pytest.raises(QdrantSchemaMismatch, match="(?i)named|hybrid|unnamed"):
            validate_collection_schema(info, enable_hybrid=False)


# ---------------------------------------------------------------------------
# Hybrid mode failure modes
# ---------------------------------------------------------------------------


class TestHybridFailures:
    def test_unnamed_vector_in_hybrid_mode_raises(self):
        """Phase 1 collection (unnamed dense) passed to hybrid mode must raise.

        This is the Phase-2 refusal test: code with enable_hybrid=True must
        detect a Phase 1 collection and refuse BEFORE any Qdrant I/O.
        """
        from qdrant_doctor.schema import QdrantSchemaMismatch, validate_collection_schema

        info = _dense_only_collection()
        with pytest.raises(QdrantSchemaMismatch, match="(?i)named|hybrid|dense"):
            validate_collection_schema(info, enable_hybrid=True)

    def test_hybrid_missing_dense_vector_raises(self):
        """Hybrid collection without named 'dense' vector must raise."""
        from qdrant_doctor.schema import QdrantSchemaMismatch, validate_collection_schema

        # Named vectors, but NOT named 'dense'
        info = _make_collection_info(
            vectors={"text": VectorParams(size=1024, distance=Distance.COSINE)},
            sparse_vectors={"bm25": SparseVectorParams(index=SparseIndexParams(on_disk=False))},
        )
        with pytest.raises(QdrantSchemaMismatch, match="(?i)dense"):
            validate_collection_schema(info, enable_hybrid=True)

    def test_hybrid_missing_sparse_vector_raises(self):
        """Hybrid mode but no sparse vector config must raise."""
        from qdrant_doctor.schema import QdrantSchemaMismatch, validate_collection_schema

        info = _hybrid_collection(include_sparse=False)
        with pytest.raises(QdrantSchemaMismatch, match="(?i)sparse|bm25"):
            validate_collection_schema(info, enable_hybrid=True)

    def test_hybrid_dense_wrong_size_raises(self):
        """Hybrid collection with named 'dense' vector of wrong size must raise."""
        from qdrant_doctor.schema import QdrantSchemaMismatch, validate_collection_schema

        info = _hybrid_collection(dense_size=512)
        with pytest.raises(QdrantSchemaMismatch, match="512"):
            validate_collection_schema(info, enable_hybrid=True)

    def test_hybrid_dense_wrong_distance_raises(self):
        """Hybrid collection with named 'dense' vector and wrong distance must raise."""
        from qdrant_doctor.schema import QdrantSchemaMismatch, validate_collection_schema

        info = _hybrid_collection(dense_distance=Distance.EUCLID)
        with pytest.raises(QdrantSchemaMismatch, match="(?i)euclid|distance"):
            validate_collection_schema(info, enable_hybrid=True)


# ---------------------------------------------------------------------------
# Error message quality
# ---------------------------------------------------------------------------


class TestErrorMessages:
    def test_size_error_includes_actual_and_expected(self):
        """Error message must include both actual size and expected 1024."""
        from qdrant_doctor.schema import QdrantSchemaMismatch, validate_collection_schema

        info = _dense_only_collection(size=384)
        with pytest.raises(QdrantSchemaMismatch) as exc_info:
            validate_collection_schema(info, enable_hybrid=False)
        msg = str(exc_info.value)
        assert "384" in msg
        assert "1024" in msg

    def test_exception_is_subclass_of_value_error(self):
        """QdrantSchemaMismatch must be catchable as ValueError for broad compatibility."""
        from qdrant_doctor.schema import QdrantSchemaMismatch

        assert issubclass(QdrantSchemaMismatch, ValueError)
