"""Qdrant collection schema validator for the WorldView platform.

Phase 1 runtime contract (dense-only):
  - Single UNNAMED vector, size=1024, distance=Cosine.

Phase 2 runtime contract (hybrid):
  - Named ``dense`` vector, size=1024, distance=Cosine.
  - At least one sparse vector config (BM25/SPLADE).

``validate_collection_schema`` raises ``QdrantSchemaMismatch`` on any violation.
It must be called BEFORE any Qdrant write or search operation so schema drift
is detected early, not at query-time.
"""

from __future__ import annotations

from collections.abc import Mapping

from qdrant_client.models import (
    CollectionInfo,
    Distance,
    PayloadIndexInfo,
    PayloadSchemaType,
    VectorParams,
)

__all__ = [
    "PAYLOAD_INDEXES",
    "QdrantSchemaMismatch",
    "missing_payload_indexes",
    "validate_collection_schema",
    "validate_payload_index_schema",
]

PAYLOAD_INDEXES: dict[str, str] = {
    "source": "keyword",
    "telegram_channel": "keyword",
    "notebook_id": "keyword",
    "feed_name": "keyword",
    "url": "keyword",
    "fulltext_article_id": "keyword",
    "fulltext_status": "keyword",
    "superseded_by_fulltext": "bool",
    "fulltext_retry_epoch": "float",
    "spatial_about_scope_revision_tokens": "keyword",
    "spatial_occurrence_scope_revision_tokens": "keyword",
    "geo": "geo",
    "spatial_basis": "keyword",
    "spatial_precision": "keyword",
    "spatial_catalog_revision": "keyword",
    "spatial_projection_revision": "keyword",
    "spatial_derivation_version": "keyword",
}

EXPECTED_DENSE_SIZE = 1024
EXPECTED_DISTANCE = Distance.COSINE
NAMED_DENSE_KEY = "dense"


class QdrantSchemaMismatch(ValueError):  # noqa: N818 — legacy name; rename is a separate API change
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
        info:          CollectionInfo returned by ``QdrantClient.get_collection()``.
        enable_hybrid: If True, expect Phase 2 schema (named dense + sparse).
                       If False, expect Phase 1 schema (unnamed dense vector).

    Raises:
        QdrantSchemaMismatch: On ANY schema violation with a human-readable message
                              that includes the actual and expected values.
    """
    params = info.config.params
    vectors = params.vectors  # Union[VectorParams, dict[str, VectorParams]]
    sparse_vectors = params.sparse_vectors  # dict[str, SparseVectorParams] | None

    if enable_hybrid:
        _validate_hybrid(vectors, sparse_vectors)
    else:
        _validate_dense_only(vectors)
    validate_payload_index_schema(info)


def missing_payload_indexes(info: object) -> list[str]:
    """Return required payload-index fields absent from the collection."""

    existing = set((getattr(info, "payload_schema", None) or {}).keys())
    return [field for field in PAYLOAD_INDEXES if field not in existing]


def validate_payload_index_schema(info: object) -> list[str]:
    """Reject wrong existing types and report missing indexes without writing."""

    payload_schema = getattr(info, "payload_schema", None) or {}
    if not isinstance(payload_schema, Mapping):
        raise QdrantSchemaMismatch("Qdrant payload schema is not a field mapping")

    mismatches: list[str] = []
    for field, expected in PAYLOAD_INDEXES.items():
        if field not in payload_schema:
            continue
        actual = _payload_index_type(payload_schema[field])
        if actual != expected:
            mismatches.append(f"{field}: existing {actual}, expected {expected}")
    if mismatches:
        raise QdrantSchemaMismatch(
            "Qdrant payload index type mismatch: " + "; ".join(mismatches)
        )
    return missing_payload_indexes(info)


def _payload_index_type(value: object) -> str:
    data_type: object
    if isinstance(value, PayloadIndexInfo):
        data_type = value.data_type
    elif isinstance(value, Mapping):
        data_type = value.get("data_type")
    else:
        data_type = getattr(value, "data_type", None)
    if isinstance(data_type, PayloadSchemaType):
        return data_type.value
    if isinstance(data_type, str):
        return data_type
    return f"unrecognized({type(value).__name__})"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _validate_dense_only(vectors) -> None:  # type: ignore[type-arg]
    """Validate Phase 1: single unnamed dense vector."""
    # Must NOT be a named-vector dict — hybrid schema is not accepted
    if isinstance(vectors, dict):
        raise QdrantSchemaMismatch(
            "dense-only mode expects an unnamed vector, but the collection uses named "
            f"vectors: {list(vectors.keys())}. "
            "This looks like a hybrid (Phase 2) collection. "
            "Set enable_hybrid=True or migrate to the correct collection."
        )

    # At this point vectors is a single VectorParams
    _check_dense_params(vectors, label="unnamed")


def _validate_hybrid(vectors, sparse_vectors) -> None:  # type: ignore[type-arg]
    """Validate Phase 2: named 'dense' vector + at least one sparse vector config."""
    # Must be a named-vector dict
    if not isinstance(vectors, dict):
        raise QdrantSchemaMismatch(
            "hybrid mode expects a named 'dense' vector, but the collection has "
            "a single unnamed dense vector (Phase 1 schema). "
            "Migrate the collection to the Phase 2 schema before enabling hybrid search."
        )

    # Named 'dense' vector must exist
    if NAMED_DENSE_KEY not in vectors:
        raise QdrantSchemaMismatch(
            f"hybrid mode requires a vector named '{NAMED_DENSE_KEY}', "
            f"but only found: {list(vectors.keys())}."
        )

    _check_dense_params(vectors[NAMED_DENSE_KEY], label=f"named '{NAMED_DENSE_KEY}'")

    # Sparse vector config must exist
    if not sparse_vectors:
        raise QdrantSchemaMismatch(
            "hybrid mode requires at least one sparse vector config (BM25/SPLADE), "
            "but sparse_vectors is absent or empty. "
            "Add a sparse vector config to the collection before enabling hybrid search."
        )


def _check_dense_params(params: VectorParams, *, label: str) -> None:
    """Check size and distance of a dense VectorParams, raising on mismatch."""
    if params.size != EXPECTED_DENSE_SIZE:
        raise QdrantSchemaMismatch(
            f"Expected {label} vector size {EXPECTED_DENSE_SIZE}, "
            f"got {params.size}. "
            "The TEI embedding model produces 1024-dimensional vectors. "
            "Recreate the collection with the correct dimension."
        )

    actual_distance = params.distance
    if actual_distance != EXPECTED_DISTANCE:
        shown = actual_distance.value if hasattr(actual_distance, "value") else actual_distance
        raise QdrantSchemaMismatch(
            f"Expected {label} vector distance {EXPECTED_DISTANCE.value} (Cosine), "
            f"got {shown}. "
            "The platform uses cosine similarity throughout. "
            "Recreate the collection with distance=Cosine."
        )
