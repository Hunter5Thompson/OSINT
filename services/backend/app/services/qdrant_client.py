"""Lazy async Qdrant client singleton with startup schema validation.

On first access, the schema of the configured collection is validated against
the expected runtime contract (dense-only Phase 1).  Any mismatch raises
``QdrantSchemaMismatch`` before the first search or write, preventing silent
data-corruption from schema drift.
"""

from qdrant_client import AsyncQdrantClient

from app.config import settings
from app.services.qdrant_schema import QdrantSchemaMismatch, validate_collection_schema

_client: AsyncQdrantClient | None = None
_schema_validated: bool = False

__all__ = ["close_qdrant_client", "get_qdrant_client", "QdrantSchemaMismatch"]


async def get_qdrant_client() -> AsyncQdrantClient:
    """Return a module-cached async Qdrant client.

    On the first call, validates that the configured collection's vector schema
    matches the active runtime mode.  Raises ``QdrantSchemaMismatch`` if the
    schema is wrong, preventing any reads or writes against a misconfigured
    collection.
    """
    global _client, _schema_validated
    if _client is None:
        _client = AsyncQdrantClient(url=settings.qdrant_url)
    if not _schema_validated:
        _schema_validated = await _validate_schema(_client)
    return _client


async def close_qdrant_client() -> None:
    """Release and reset the cached client."""
    global _client, _schema_validated
    client, _client = _client, None
    _schema_validated = False
    if client is not None:
        await client.close()


async def _validate_schema(client: AsyncQdrantClient) -> bool:
    """Fetch and validate collection info. Return whether validation completed."""
    try:
        collections = await client.get_collections()
        names = {c.name for c in collections.collections}
        if settings.qdrant_collection not in names:
            # Collection absent — nothing to validate; let callers handle 404
            return True
        info = await client.get_collection(settings.qdrant_collection)
        enable_hybrid: bool = getattr(settings, "enable_hybrid", False)
        validate_collection_schema(info, enable_hybrid=enable_hybrid)
    except QdrantSchemaMismatch:
        raise
    except Exception:
        # Network errors etc. — don't block startup; let operations fail naturally
        return False
    return True
