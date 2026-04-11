"""Lazy async Qdrant client singleton."""

from qdrant_client import AsyncQdrantClient

from app.config import settings

_client: AsyncQdrantClient | None = None


async def get_qdrant_client() -> AsyncQdrantClient:
    """Return a module-cached async Qdrant client."""
    global _client
    if _client is None:
        _client = AsyncQdrantClient(url=settings.qdrant_url)
    return _client
