"""Qdrant vector search tool for RAG retrieval."""

import httpx
import structlog
from langchain_core.tools import tool

from config import settings

logger = structlog.get_logger()


@tool
async def qdrant_search(query: str, region: str = "") -> str:
    """Search the intelligence knowledge base for relevant documents.

    Args:
        query: The search query.
        region: Optional region filter (e.g., 'Middle East', 'East Asia').

    Returns:
        Relevant documents from the knowledge base.
    """
    try:
        # Generate embedding for the query
        embedding = await _get_embedding(query)
        if not embedding:
            return "Failed to generate query embedding."

        # Search Qdrant
        search_body: dict = {
            "vector": embedding,
            "limit": 5,
            "with_payload": True,
        }

        if region:
            search_body["filter"] = {
                "must": [{"key": "region", "match": {"value": region}}]
            }

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{settings.qdrant_url}/collections/{settings.qdrant_collection}/points/search",
                json=search_body,
            )

            if resp.status_code == 404:
                return "Knowledge base collection not found. Run data ingestion first."

            resp.raise_for_status()
            data = resp.json()

        results = data.get("result", [])
        if not results:
            return f"No relevant documents found for: {query}"

        formatted: list[str] = []
        for r in results:
            payload = r.get("payload", {})
            score = r.get("score", 0)
            formatted.append(
                f"[Score: {score:.3f}] {payload.get('title', 'Untitled')}\n"
                f"Source: {payload.get('source', 'unknown')} | "
                f"Region: {payload.get('region', 'N/A')}\n"
                f"{payload.get('content', '')[:300]}\n"
            )

        return f"[Knowledge Base Results for: {query}]\n" + "\n---\n".join(formatted)
    except Exception as e:
        logger.warning("qdrant_search_failed", error=str(e))
        return f"Knowledge base search failed: {e}"


async def _get_embedding(text: str) -> list[float] | None:
    """Generate embedding via Ollama API."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{settings.ollama_url}/api/embed",
                json={"model": settings.embedding_model, "input": text},
            )
            resp.raise_for_status()
            data = resp.json()
            embeddings = data.get("embeddings", [])
            if embeddings:
                return embeddings[0]
    except Exception as e:
        logger.warning("embedding_failed", error=str(e))
    return None
