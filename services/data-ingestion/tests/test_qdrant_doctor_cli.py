"""TDD tests for the Qdrant doctor CLI.

All tests mock the QdrantClient — no live Qdrant required.
"""

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
# Helpers to build mocked Qdrant client
# ---------------------------------------------------------------------------


def _make_collection_info(
    *,
    vectors,
    sparse_vectors=None,
    points_count: int = 42,
) -> CollectionInfo:
    """Build CollectionInfo via model_construct to bypass strict pydantic validation."""
    params = CollectionParams.model_construct(vectors=vectors, sparse_vectors=sparse_vectors)
    config = CollectionConfig.model_construct(params=params)
    return CollectionInfo.model_construct(
        config=config,
        payload_schema={},
        points_count=points_count,
    )


def _dense_only_info(size: int = 1024, distance: Distance = Distance.COSINE):
    return _make_collection_info(vectors=VectorParams(size=size, distance=distance))


def _hybrid_info():
    return _make_collection_info(
        vectors={"dense": VectorParams(size=1024, distance=Distance.COSINE)},
        sparse_vectors={"bm25": SparseVectorParams(index=SparseIndexParams(on_disk=False))},
    )


def _mock_qdrant_with_collection(info):
    """Return a mock QdrantClient that has the collection and returns info."""
    mock = MagicMock()

    # collections list
    coll = MagicMock()
    coll.name = "odin_intel"
    mock.get_collections.return_value.collections = [coll]
    mock.get_collection.return_value = info
    return mock


def _mock_qdrant_empty():
    """Return a mock QdrantClient with NO collections."""
    mock = MagicMock()
    mock.get_collections.return_value.collections = []
    return mock


# ---------------------------------------------------------------------------
# Doctor CLI: happy path (exit 0)
# ---------------------------------------------------------------------------


class TestDoctorHappyPath:
    def test_dense_only_valid_exits_zero(self, capsys):
        """Valid dense-only collection → exit 0, prints status."""
        from qdrant_doctor.cli import run_doctor

        mock_client = _mock_qdrant_with_collection(_dense_only_info())
        with patch("qdrant_doctor.cli.QdrantClient", return_value=mock_client):
            exit_code = run_doctor(
                qdrant_url="http://localhost:6333",
                collection_name="odin_intel",
                enable_hybrid=False,
            )

        assert exit_code == 0
        out = capsys.readouterr().out
        assert "odin_intel" in out
        assert "42" in out  # point count

    def test_hybrid_disabled_v2_absent_is_warning_not_failure(self, capsys):
        """odin_v2 absent + hybrid disabled → WARN only, exit 0."""
        from qdrant_doctor.cli import run_doctor

        # Only odin_intel exists, not odin_v2
        mock_client = _mock_qdrant_with_collection(_dense_only_info())
        with patch("qdrant_doctor.cli.QdrantClient", return_value=mock_client):
            exit_code = run_doctor(
                qdrant_url="http://localhost:6333",
                collection_name="odin_intel",
                enable_hybrid=False,
                v2_collection="odin_v2",
            )

        assert exit_code == 0
        out = capsys.readouterr().out
        assert "WARN" in out.upper() or "warn" in out.lower()


# ---------------------------------------------------------------------------
# Doctor CLI: failure cases (non-zero exit)
# ---------------------------------------------------------------------------


class TestDoctorFailureCases:
    def test_collection_missing_dense_only_fails(self):
        """Primary collection missing in dense-only mode → non-zero exit."""
        from qdrant_doctor.cli import run_doctor

        mock_client = _mock_qdrant_empty()
        with patch("qdrant_doctor.cli.QdrantClient", return_value=mock_client):
            exit_code = run_doctor(
                qdrant_url="http://localhost:6333",
                collection_name="odin_intel",
                enable_hybrid=False,
            )

        assert exit_code != 0

    def test_hybrid_enabled_sparse_missing_fails(self):
        """Hybrid enabled but sparse vector config absent → non-zero exit."""
        from qdrant_doctor.cli import run_doctor

        # Named dense only, no sparse
        no_sparse_info = _make_collection_info(
            vectors={"dense": VectorParams(size=1024, distance=Distance.COSINE)},
            sparse_vectors=None,
        )
        mock_client = _mock_qdrant_with_collection(no_sparse_info)
        with patch("qdrant_doctor.cli.QdrantClient", return_value=mock_client):
            exit_code = run_doctor(
                qdrant_url="http://localhost:6333",
                collection_name="odin_intel",
                enable_hybrid=True,
            )

        assert exit_code != 0

    def test_dense_size_not_1024_fails(self):
        """Dense vector size != 1024 → non-zero exit."""
        from qdrant_doctor.cli import run_doctor

        mock_client = _mock_qdrant_with_collection(_dense_only_info(size=768))
        with patch("qdrant_doctor.cli.QdrantClient", return_value=mock_client):
            exit_code = run_doctor(
                qdrant_url="http://localhost:6333",
                collection_name="odin_intel",
                enable_hybrid=False,
            )

        assert exit_code != 0

    def test_distance_not_cosine_fails(self):
        """Dense distance != Cosine → non-zero exit."""
        from qdrant_doctor.cli import run_doctor

        mock_client = _mock_qdrant_with_collection(
            _dense_only_info(distance=Distance.EUCLID)
        )
        with patch("qdrant_doctor.cli.QdrantClient", return_value=mock_client):
            exit_code = run_doctor(
                qdrant_url="http://localhost:6333",
                collection_name="odin_intel",
                enable_hybrid=False,
            )

        assert exit_code != 0

    def test_hybrid_enabled_named_dense_missing_fails(self):
        """Hybrid enabled but named 'dense' vector absent → non-zero exit."""
        from qdrant_doctor.cli import run_doctor

        # Only unnamed dense — Phase 1 schema passed to hybrid mode
        mock_client = _mock_qdrant_with_collection(_dense_only_info())
        with patch("qdrant_doctor.cli.QdrantClient", return_value=mock_client):
            exit_code = run_doctor(
                qdrant_url="http://localhost:6333",
                collection_name="odin_intel",
                enable_hybrid=True,
            )

        assert exit_code != 0


# ---------------------------------------------------------------------------
# Doctor CLI: output content
# ---------------------------------------------------------------------------


class TestDoctorOutput:
    def test_output_includes_schema_summary(self, capsys):
        """Doctor output must include collection name, point count, and vector info."""
        from qdrant_doctor.cli import run_doctor

        mock_client = _mock_qdrant_with_collection(_dense_only_info())
        with patch("qdrant_doctor.cli.QdrantClient", return_value=mock_client):
            run_doctor(
                qdrant_url="http://localhost:6333",
                collection_name="odin_intel",
                enable_hybrid=False,
            )

        out = capsys.readouterr().out
        assert "odin_intel" in out
        assert "1024" in out
        assert "Cosine" in out or "cosine" in out.lower()

    def test_failure_output_includes_error_description(self, capsys):
        """On failure, doctor must print a meaningful error."""
        from qdrant_doctor.cli import run_doctor

        mock_client = _mock_qdrant_with_collection(_dense_only_info(size=512))
        with patch("qdrant_doctor.cli.QdrantClient", return_value=mock_client):
            run_doctor(
                qdrant_url="http://localhost:6333",
                collection_name="odin_intel",
                enable_hybrid=False,
            )

        out = capsys.readouterr().out
        assert "512" in out or "FAIL" in out.upper()
