"""Qdrant vector search tool for RAG retrieval."""

import structlog
from langchain_core.tools import tool

from rag.retriever import enhanced_search

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
        results = await enhanced_search(
            query,
            limit=5,
            region=region or None,
        )

        if not results:
            return f"No relevant documents found for: {query}"

        formatted: list[str] = []
        for r in results:
            score = r.get("score", 0)
            title = r.get("title", "Untitled")
            source = r.get("source", "unknown")
            region_val = r.get("region", "N/A")
            content = r.get("content", "")[:300]

            entry = (
                f"[Score: {score:.3f}] {title}\n"
                f"Source: {source} | Region: {region_val}\n"
                f"{content}\n"
            )

            # Append graph context if available
            graph_ctx = r.get("graph_context", "")
            if graph_ctx:
                entry += f"\n{graph_ctx}\n"

            formatted.append(entry)

        return f"[Knowledge Base Results for: {query}]\n" + "\n---\n".join(formatted)
    except Exception as e:
        logger.warning("qdrant_search_failed", error=str(e))
        return f"Knowledge base search failed: {e}"
