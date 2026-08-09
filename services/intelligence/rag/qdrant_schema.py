"""Qdrant collection schema validator for the WorldView intelligence service.

Service-local copy — each service owns its validator independently.

Phase 1 runtime contract (dense-only):
  - Single UNNAMED vector, size=1024, distance=Cosine.

Phase 2 runtime contract (hybrid):
  - Named ``dense`` vector, size=1024, distance=Cosine.
  - At least one sparse vector config (BM25/SPLADE).
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
    "QdrantSchemaMismatch",
    "validate_collection_schema",
    "PAYLOAD_INDEXES",
    "REQUIRED_PAYLOAD_INDEXES",
    "missing_payload_indexes",
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
    "spatial_conflict": "bool",
    "spatial_conflict_scope_keys": "keyword",
}
REQUIRED_PAYLOAD_INDEXES = tuple(PAYLOAD_INDEXES)   # field names (back-compat)


def missing_payload_indexes(info) -> list[str]:
    """Return required payload-index fields absent from the collection.
    Read-only: callers warn; the migration script (scripts/ensure_payload_indexes)
    is the only writer."""
    existing = set((getattr(info, "payload_schema", None) or {}).keys())
    return [f for f in REQUIRED_PAYLOAD_INDEXES if f not in existing]


def validate_payload_index_schema(info: object) -> list[str]:
    """Reject wrong existing index types and return absent required fields.

    This function is read-only.  Missing indexes are reported to callers, while a
    present field with the wrong Qdrant type fails closed because creating another
    index cannot repair that drift safely.
    """

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


EXPECTED_DENSE_SIZE = 1024
EXPECTED_DISTANCE = Distance.COSINE
NAMED_DENSE_KEY = "dense"


class QdrantSchemaMismatch(ValueError):  # noqa: N818 — legacy name; rename is a separate API change
    """Raised when a Qdrant collection's vector schema does not match expectations."""


def validate_collection_schema(
    info: CollectionInfo,
    *,
    enable_hybrid: bool,
) -> None:
    """Validate that *info* matches the expected schema for *enable_hybrid* mode.

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
    validate_payload_index_schema(info)


def _validate_dense_only(vectors) -> None:  # type: ignore[type-arg]
    if isinstance(vectors, dict):
        raise QdrantSchemaMismatch(
            "dense-only mode expects an unnamed vector, but the collection uses named "
            f"vectors: {list(vectors.keys())}. "
            "This looks like a hybrid (Phase 2) collection."
        )
    _check_dense_params(vectors, label="unnamed")


def _validate_hybrid(vectors, sparse_vectors) -> None:  # type: ignore[type-arg]
    if not isinstance(vectors, dict):
        raise QdrantSchemaMismatch(
            "hybrid mode expects a named 'dense' vector, but the collection has "
            "a single unnamed dense vector (Phase 1 schema)."
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
            f"Expected {label} vector size {EXPECTED_DENSE_SIZE}, got {params.size}."
        )
    actual_distance = params.distance
    if actual_distance != EXPECTED_DISTANCE:
        shown = actual_distance.value if hasattr(actual_distance, "value") else actual_distance
        raise QdrantSchemaMismatch(
            f"Expected {label} vector distance {EXPECTED_DISTANCE.value} (Cosine), "
            f"got {shown}."
        )
