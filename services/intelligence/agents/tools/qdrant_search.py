"""Qdrant vector search tool for RAG retrieval."""

import structlog
from langchain_core.tools import tool

from rag.retriever import enhanced_search

logger = structlog.get_logger()

RESULT_CONTENT_MAX_CHARS = 300
GRAPH_CONTEXT_MAX_CHARS = 1200
TOOL_OUTPUT_MAX_CHARS = 3500


def _clip_text(text: str, max_chars: int) -> str:
    """Keep tool outputs bounded so ReAct history stays inside model context."""
    if len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    return text[:max_chars].rstrip() + f"\n...[truncated {omitted} chars]"


@tool
async def qdrant_search(query: str, region: str = "") -> str:
    """Semantic vector search across the OSINT knowledge base.

    Index content (≈20k documents, 1024-dim cosine):
    - 37 RSS feeds (Reuters, BBC, AP, BMVg, Bundeswehr, Bundestag, SWP, RUSI,
      EU Parliament Security and Defence, NATO/UN/US Gov, defense media, etc.)
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
        graph_contexts: list[str] = []
        seen_graph_contexts: set[str] = set()
        for r in results:
            score = r.get("score", 0)
            title = r.get("title", "Untitled")
            source = r.get("source", "unknown")
            region_val = r.get("region", "N/A")
            content = _clip_text(str(r.get("content", "")), RESULT_CONTENT_MAX_CHARS)

            entry = (
                f"[Score: {score:.3f}] {title}\n"
                f"Source: {source} | Region: {region_val}\n"
                f"{content}\n"
            )

            # enhanced_search currently attaches the same graph context to each
            # result. Keep it once, otherwise three qdrant_search calls can fill
            # a 16k-token model window before synthesis even starts.
            graph_ctx = r.get("graph_context", "")
            if graph_ctx and graph_ctx not in seen_graph_contexts:
                seen_graph_contexts.add(graph_ctx)
                graph_contexts.append(_clip_text(str(graph_ctx), GRAPH_CONTEXT_MAX_CHARS))

            formatted.append(entry)

        output = f"[Knowledge Base Results for: {query}]\n" + "\n---\n".join(formatted)
        if graph_contexts:
            output += "\n---\n[Graph Context]\n" + "\n\n".join(graph_contexts)
        return _clip_text(output, TOOL_OUTPUT_MAX_CHARS)
    except Exception as e:
        logger.warning("qdrant_search_failed", error=str(e))
        return f"Knowledge base search failed: {e}"
