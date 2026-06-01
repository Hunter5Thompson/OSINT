"""Qdrant vector search tool for RAG retrieval."""

import structlog
from langchain_core.tools import tool

from rag.evidence import format_evidence_pack, to_evidence_item
from rag.retriever import enhanced_search

logger = structlog.get_logger()

GRAPH_CONTEXT_MAX_CHARS = 1200
TOOL_OUTPUT_MAX_CHARS = 6500


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
    - NotebookLM extractions from briefing audio and research reports

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
        A budgeted evidence pack: one `[EVIDENCE] {json}` metadata line per hit
        (provider, source_type, credibility_score, published_at, url, ...) followed
        by Title/Excerpt lines, optionally followed by a deduplicated [Graph Context]
        block. Sorted by relevance; bounded by an internal character budget.
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

        items = [to_evidence_item(r) for r in results]

        # Graph context is deduped and appended AFTER evidence within remaining budget.
        graph_blocks: list[str] = []
        seen_graph: set[str] = set()
        for r in results:
            gctx = r.get("graph_context", "")
            if gctx and gctx not in seen_graph:
                seen_graph.add(gctx)
                graph_blocks.append(_clip_text(str(gctx), GRAPH_CONTEXT_MAX_CHARS))

        graph_text = ""
        if graph_blocks:
            graph_text = "\n---\n[Graph Context]\n" + "\n\n".join(graph_blocks)

        header = f"[Knowledge Base Evidence for: {query}]\n"
        evidence_budget = TOOL_OUTPUT_MAX_CHARS - len(graph_text) - len(header)
        pack = format_evidence_pack(items, budget=max(evidence_budget, 0))
        output = header + pack
        if graph_text and len(output) + len(graph_text) <= TOOL_OUTPUT_MAX_CHARS:
            output += graph_text
        return output
    except Exception as e:
        logger.warning("qdrant_search_failed", error=str(e))
        return f"Knowledge base search failed: {e}"
