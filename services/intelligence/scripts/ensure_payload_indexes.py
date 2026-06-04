"""Idempotent migration: create keyword payload indexes required by the
read-corpus filter. Run once before relying on filtered search — Qdrant needs an
HNSW rebuild to fully use filter-aware links for indexes added after points
exist. Safe to re-run.

Usage:  uv run python -m scripts.ensure_payload_indexes
"""
from __future__ import annotations

import asyncio

import structlog

from config import settings
from rag.qdrant_schema import PAYLOAD_INDEXES

log = structlog.get_logger(__name__)


async def ensure_indexes(*, client=None, collection: str | None = None) -> list[str]:
    own_client = client is None
    if own_client:
        from qdrant_client import AsyncQdrantClient
        client = AsyncQdrantClient(url=settings.qdrant_url)
    collection = collection or settings.qdrant_collection
    try:
        info = await client.get_collection(collection)
        existing = set((info.payload_schema or {}).keys())
        created: list[str] = []
        for field, schema in PAYLOAD_INDEXES.items():
            if field in existing:
                continue
            await client.create_payload_index(
                collection_name=collection,
                field_name=field,
                field_schema=schema,
                wait=True,
            )
            created.append(field)
        log.info("payload_indexes_ensured", created=created,
                 already_present=sorted(existing & set(PAYLOAD_INDEXES)))
        return created
    finally:
        if own_client:
            await client.close()


if __name__ == "__main__":
    print(asyncio.run(ensure_indexes()))
