"""Qdrant vector search tool for RAG retrieval."""

import structlog
from langchain_core.tools import tool

from rag.corpus_policy import (
    ANALYSIS_POOL,
    FINAL_K,
    REALTIME_POOL,
    RT_SCORE_THRESHOLD,
    TELEGRAM_MAX,
    analysis_filter,
    apply_tier_boost,
    merge_lanes,
    realtime_filter,
    validate_lane,
)
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

    Index content — VETTED ANALYSIS PROSE only (1024-dim cosine):
    - 37 RSS feeds: think-tanks (CSIS, RUSI, RAND, SIPRI, SWP, Atlantic Council,
      War on the Rocks, Brookings, Crisis Group, Bellingcat), gov/mil (BMVg,
      Bundeswehr, Bundestag, NATO, UN, US Gov), wire (Reuters, AP, BBC), defense media
    - NotebookLM extractions from briefing audio and research reports
    Plus AT MOST ONE vetted Telegram realtime LEAD (wartranslated, OSINTdefender,
    liveuamap, AuroraIntel, DeepStateEN), marked source_class="realtime" — treat it
    as an unverified lead, not a primary source.

    NOT here: GDELT-GKG, FIRMS, UCDP, GDACS, EONET and other structured/sensor data
    — reach those via query_knowledge_graph (Neo4j), not this tool.

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
        analysis = await enhanced_search(
            query, limit=FINAL_K, pool=ANALYSIS_POOL,
            query_filter=analysis_filter(), region=region or None,
            post_rerank=apply_tier_boost,
        )
        try:
            realtime = await enhanced_search(
                query, limit=TELEGRAM_MAX, pool=REALTIME_POOL,
                query_filter=realtime_filter(), region=region or None,
                post_rerank=apply_tier_boost, score_threshold=RT_SCORE_THRESHOLD,
            )
        except Exception as e:  # realtime is best-effort; never fail the analysis lane
            logger.warning("realtime_lane_failed", query=query, error=str(e))
            realtime = []

        analysis = validate_lane(analysis, "analysis")
        realtime = validate_lane(realtime, "realtime")
        results = merge_lanes(analysis, realtime)

        logger.info(
            "qdrant_search_executed",
            query=query,
            analysis_count=len(analysis),
            realtime_count=len(realtime),
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
        pack = format_evidence_pack(
            items, budget=max(evidence_budget, 0), preserve_order=True)
        output = header + pack
        if graph_text and len(output) + len(graph_text) <= TOOL_OUTPUT_MAX_CHARS:
            output += graph_text
        return output
    except Exception as e:
        logger.warning("qdrant_search_failed", error=str(e))
        return f"Knowledge base search failed: {e}"
