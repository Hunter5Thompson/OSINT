"""Qdrant retriever for hybrid search with payload filtering."""

import httpx
import structlog

from config import settings
from rag.embedder import embed_text

logger = structlog.get_logger()


async def search(
    query: str,
    limit: int = 5,
    region: str | None = None,
    source: str | None = None,
    score_threshold: float = 0.3,
) -> list[dict]:
    """Search the knowledge base with optional filters.

    Args:
        query: Search query text.
        limit: Maximum number of results.
        region: Optional region filter.
        source: Optional source filter.
        score_threshold: Minimum similarity score.

    Returns:
        List of matching documents with scores.
    """
    embedding = await embed_text(query)
    if not embedding:
        return []

    search_body: dict = {
        "vector": embedding,
        "limit": limit,
        "with_payload": True,
        "score_threshold": score_threshold,
    }

    # Build filter conditions
    must_conditions: list[dict] = []
    if region:
        must_conditions.append({"key": "region", "match": {"value": region}})
    if source:
        must_conditions.append({"key": "source", "match": {"value": source}})

    if must_conditions:
        search_body["filter"] = {"must": must_conditions}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{settings.qdrant_url}/collections/{settings.qdrant_collection}/points/search",
                json=search_body,
            )
            if resp.status_code == 404:
                logger.warning("collection_not_found")
                return []
            resp.raise_for_status()
            data = resp.json()

        results: list[dict] = []
        for r in data.get("result", []):
            results.append({
                "score": r.get("score", 0),
                **r.get("payload", {}),
            })

        return results
    except Exception as e:
        logger.warning("retriever_search_failed", error=str(e))
        return []
