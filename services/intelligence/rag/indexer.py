"""Qdrant indexing pipeline for document ingestion."""

import uuid

import httpx
import structlog

from config import settings
from rag.chunker import chunk_text
from rag.embedder import embed_text

logger = structlog.get_logger()


async def ensure_collection() -> None:
    """Create the Qdrant collection if it doesn't exist."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{settings.qdrant_url}/collections/{settings.qdrant_collection}"
        )
        if resp.status_code == 200:
            return

        await client.put(
            f"{settings.qdrant_url}/collections/{settings.qdrant_collection}",
            json={
                "vectors": {"size": settings.embedding_dimensions, "distance": "Cosine"},
            },
        )
        logger.info("qdrant_collection_created", name=settings.qdrant_collection)


async def ingest_document(
    title: str,
    content: str,
    source: str,
    region: str | None = None,
    hotspot_ids: list[str] | None = None,
    published_at: str | None = None,
) -> int:
    """Ingest a document into Qdrant: chunk → embed → upsert.

    Returns:
        Number of chunks indexed.
    """
    await ensure_collection()

    chunks = chunk_text(content)
    points: list[dict] = []

    for i, chunk in enumerate(chunks):
        embedding = await embed_text(chunk)
        if not embedding:
            continue

        point_id = str(uuid.uuid4())
        points.append({
            "id": point_id,
            "vector": embedding,
            "payload": {
                "title": title,
                "content": chunk,
                "source": source,
                "region": region or "",
                "hotspot_ids": hotspot_ids or [],
                "published_at": published_at or "",
                "chunk_index": i,
                "total_chunks": len(chunks),
            },
        })

    if not points:
        return 0

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.put(
            f"{settings.qdrant_url}/collections/{settings.qdrant_collection}/points",
            json={"points": points},
        )
        resp.raise_for_status()

    logger.info("document_ingested", title=title, chunks=len(points))
    return len(points)
