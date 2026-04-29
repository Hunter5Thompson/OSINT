"""Qdrant vector search tool for RAG retrieval."""

import structlog
from langchain_core.tools import tool

from rag.retriever import enhanced_search

logger = structlog.get_logger()


@tool
async def qdrant_search(query: str, region: str = "") -> str:
    """Semantic vector search across the OSINT knowledge base.

    Index content (≈20k documents, 1024-dim cosine):
    - 27 RSS feeds (Reuters, BBC, AP, Al Jazeera, Defence Blog, ISW, etc.)
    - Telegram channels: OSINTdefender, DeepStateEN, wartranslated, liveuamap, rybar
    - UCDP-GED conflict events with casualty counts and locations
    - FIRMS thermal-anomaly annotations
    - GDACS disaster bulletins, EONET natural events
    - NotebookLM extractions from briefing audio

    Each result includes a graph context block (entity → relation → entity)
    derived from Neo4j — useful for spotting actors and locations connected
    to the query topic.

    Use multi-word phrases — "shadow fleet" beats "russian ships". Multi-call
    only if first call returned poor results, with a NARROWER query the second
    time (e.g. add a specific actor or location), not a region-renamed copy.

    Args:
        query: Search query in any language. Multi-word phrases work better
            than single keywords. English usually returns more hits than
            German because most feeds are English.
        region: AVOID using this — the underlying index does not currently
            populate region metadata, so any non-empty region filter returns
            zero results. Leave as empty string unless you've explicitly
            confirmed the index has region tags for your topic.

    Returns:
        Top-5 documents with score, title, source, region, content excerpt
        and a graph-context block of related entities/events.
    """
    try:
        results = await enhanced_search(
            query,
            limit=5,
            region=region or None,
        )
        logger.info(
            "qdrant_search_executed",
            query=query,
            region=region or None,
            result_count=len(results),
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
