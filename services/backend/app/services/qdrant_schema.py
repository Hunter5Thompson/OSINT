"""Qdrant collection schema validator for the WorldView backend service.

This is a service-local copy of the validator from data-ingestion/qdrant_doctor/schema.py.
Each service owns its validator independently to avoid cross-service imports.

Phase 1 runtime contract (dense-only):
  - Single UNNAMED vector, size=1024, distance=Cosine.

Phase 2 runtime contract (hybrid):
  - Named ``dense`` vector, size=1024, distance=Cosine.
  - At least one sparse vector config (BM25/SPLADE).

``validate_collection_schema`` raises ``QdrantSchemaMismatch`` on any violation.
It must be called BEFORE any Qdrant read/search operation so schema drift
is detected early, not silently ignored.
"""

from __future__ import annotations

from qdrant_client.models import CollectionInfo, Distance, VectorParams

__all__ = ["QdrantSchemaMismatch", "validate_collection_schema"]

EXPECTED_DENSE_SIZE = 1024
EXPECTED_DISTANCE = Distance.COSINE
NAMED_DENSE_KEY = "dense"


class QdrantSchemaMismatch(ValueError):
    """Raised when a Qdrant collection's vector schema does not match expectations.

    Inherits from ValueError so callers that catch broad exceptions still work.
    """


def validate_collection_schema(
    info: CollectionInfo,
    *,
    enable_hybrid: bool,
) -> None:
    """Validate that *info* matches the expected schema for *enable_hybrid* mode.

    Args:
        info:          CollectionInfo returned by ``AsyncQdrantClient.get_collection()``.
        enable_hybrid: If True, expect Phase 2 schema (named dense + sparse).
                       If False, expect Phase 1 schema (unnamed dense vector).

    Raises:
        QdrantSchemaMismatch: On ANY schema violation.
    """
    params = info.config.params
    vectors = params.vectors
    sparse_vectors = params.sparse_vectors

    if enable_hybrid:
        _validate_hybrid(vectors, sparse_vectors)
    else:
        _validate_dense_only(vectors)


def _validate_dense_only(vectors) -> None:  # type: ignore[type-arg]
    if isinstance(vectors, dict):
        raise QdrantSchemaMismatch(
            "dense-only mode expects an unnamed vector, but the collection uses named "
            f"vectors: {list(vectors.keys())}. "
            "This looks like a hybrid (Phase 2) collection. "
            "Set enable_hybrid=True or migrate to the correct collection."
        )
    _check_dense_params(vectors, label="unnamed")


def _validate_hybrid(vectors, sparse_vectors) -> None:  # type: ignore[type-arg]
    if not isinstance(vectors, dict):
        raise QdrantSchemaMismatch(
            "hybrid mode expects a named 'dense' vector, but the collection has "
            "a single unnamed dense vector (Phase 1 schema). "
            "Migrate the collection to the Phase 2 schema before enabling hybrid search."
        )
    if NAMED_DENSE_KEY not in vectors:
        raise QdrantSchemaMismatch(
            f"hybrid mode requires a vector named '{NAMED_DENSE_KEY}', "
            f"but only found: {list(vectors.keys())}."
        )
    _check_dense_params(vectors[NAMED_DENSE_KEY], label=f"named '{NAMED_DENSE_KEY}'")
    if not sparse_vectors:
        raise QdrantSchemaMismatch(
            "hybrid mode requires at least one sparse vector config (BM25/SPLADE), "
            "but sparse_vectors is absent or empty."
        )


def _check_dense_params(params: VectorParams, *, label: str) -> None:
    if params.size != EXPECTED_DENSE_SIZE:
        raise QdrantSchemaMismatch(
            f"Expected {label} vector size {EXPECTED_DENSE_SIZE}, "
            f"got {params.size}."
        )
    actual_distance = params.distance
    if actual_distance != EXPECTED_DISTANCE:
        raise QdrantSchemaMismatch(
            f"Expected {label} vector distance {EXPECTED_DISTANCE.value} (Cosine), "
            f"got {actual_distance.value if hasattr(actual_distance, 'value') else actual_distance}."
        )
