"""Qdrant vector search tool for RAG retrieval."""

import json

import structlog
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime

from graph.state import AgentState
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
from rag.evidence import neutralize_evidence_markers, pack_with_lineage, to_evidence_item
from rag.retriever import enhanced_search
from rag.spatial_coverage import (
    coverage_is_complete,
    get_spatial_coverage_snapshot,
)
from spatial import (
    ScopeKind,
    SpatialApplicationMarkerV1,
    SpatialCoverageSnapshotV1,
    combine_filters,
    compile_qdrant_scope_filter,
    format_spatial_application_marker,
)

logger = structlog.get_logger()

GRAPH_CONTEXT_MAX_CHARS = 1200
TOOL_OUTPUT_MAX_CHARS = 6500


def _qdrant_marker(
    state: AgentState,
    *,
    status: str,
    completeness: str,
    detail_code: str | None = None,
    coverage_snapshot: SpatialCoverageSnapshotV1 | None = None,
) -> SpatialApplicationMarkerV1:
    scope = state["spatial_scope"]
    scoped = scope is not None and scope.kind is not ScopeKind.WORLD
    return SpatialApplicationMarkerV1(
        consumer="qdrant",
        status=status,
        mode="semantic-key" if scoped else "global",
        completeness=completeness,
        detail_code=detail_code,
        coverage_revision=(
            coverage_snapshot.target_projection_revision
            if scoped and coverage_snapshot is not None
            else None
        ),
    )


def _with_qdrant_application(
    marker: SpatialApplicationMarkerV1,
    body: str,
) -> str:
    marker_line = format_spatial_application_marker(marker)
    body_budget = max(TOOL_OUTPUT_MAX_CHARS - len(marker_line) - 1, 0)
    return format_spatial_application_marker(marker, _clip_text(body, body_budget))


def _clip_text(text: str, max_chars: int) -> str:
    """Keep tool outputs bounded so ReAct history stays inside model context."""
    if len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    return text[:max_chars].rstrip() + f"\n...[truncated {omitted} chars]"


@tool(response_format="content_and_artifact")
async def qdrant_search(
    query: str,
    runtime: ToolRuntime[dict[str, object], AgentState],
) -> tuple[str, list[dict]]:
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

    Global results may include a graph context block (entity → relation → entity)
    derived from Neo4j. Scoped runs omit that block until graph neighborhoods can
    enforce the same scope predicate as Qdrant.

    Use multi-word phrases — "shadow fleet" beats "russian ships". Multi-call
    only if first call returned poor results, with a NARROWER query the second
    time (e.g. add a specific actor or location), not a region-renamed copy.

    Args:
        query: Search query in any language. Multi-word phrases work better
            than single keywords. English usually returns more hits than
            German because most feeds are English.
    Returns:
        A budgeted evidence pack: one `[EVIDENCE] {json}` metadata line per hit
        (provider, source_type, credibility_score, published_at, url, ...) followed
        by Title/Excerpt lines, optionally followed by a deduplicated [Graph Context]
        block. Sorted by relevance; bounded by an internal character budget.
    """
    scope = runtime.state["spatial_scope"]
    relation = runtime.state["spatial_relation"]
    scoped = scope is not None and scope.kind is not ScopeKind.WORLD
    spatial_filter = (
        compile_qdrant_scope_filter(scope, relation) if scope is not None else None
    )
    try:
        coverage_snapshot = get_spatial_coverage_snapshot() if scoped else None
        realtime_failed = False
        analysis = await enhanced_search(
            query, limit=FINAL_K, pool=ANALYSIS_POOL,
            query_filter=combine_filters(analysis_filter(), spatial_filter),
            post_rerank=apply_tier_boost,
            raise_on_failure=True,
            enable_graph_context=False if scoped else None,
            coverage_snapshot=coverage_snapshot,
        )
        try:
            realtime = await enhanced_search(
                query, limit=TELEGRAM_MAX, pool=REALTIME_POOL,
                query_filter=combine_filters(realtime_filter(), spatial_filter),
                post_rerank=apply_tier_boost, score_threshold=RT_SCORE_THRESHOLD,
                raise_on_failure=True,
                enable_graph_context=False if scoped else None,
                coverage_snapshot=coverage_snapshot,
            )
        except Exception as e:  # realtime is best-effort; never fail the analysis lane
            logger.warning("realtime_lane_failed", error=str(e))
            realtime = []
            realtime_failed = True

        analysis = validate_lane(analysis, "analysis")
        realtime = validate_lane(realtime, "realtime")
        results = merge_lanes(analysis, realtime)

        logger.info(
            "qdrant_search_executed",
            analysis_count=len(analysis),
            realtime_count=len(realtime),
            result_count=len(results),
        )

        completeness = "partial" if scoped or realtime_failed else "complete"
        detail_code = (
            "realtime-lane-failed"
            if realtime_failed
            else "coverage-snapshot-unavailable"
            if scoped and coverage_snapshot is None
            else "graph-context-omitted-for-scope" if scoped else None
        )
        marker = _qdrant_marker(
            runtime.state,
            status="applied",
            completeness=completeness,
            detail_code=detail_code,
            coverage_snapshot=coverage_snapshot,
        )

        if not results:
            coverage_text = (
                "null"
                if coverage_snapshot is None
                else json.dumps(
                    coverage_snapshot.model_dump(mode="json"),
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            if not scoped:
                empty_code = "NO_SEMANTIC_MATCHES"
            elif coverage_snapshot is None:
                empty_code = "SPATIAL_SCOPE_COVERAGE_UNAVAILABLE"
            elif coverage_is_complete(
                coverage_snapshot,
                required_lanes=("analysis", "realtime"),
            ):
                empty_code = "NO_SEMANTIC_MATCHES_IN_SCOPE"
            else:
                empty_code = "SPATIAL_SCOPE_COVERAGE_PARTIAL"
            return _with_qdrant_application(
                marker,
                f"{empty_code}: no relevant documents found for: "
                f"{neutralize_evidence_markers(query)}\n"
                f"Coverage-Snapshot: {coverage_text}",
            ), []

        items = [to_evidence_item(r) for r in results]

        # Graph context is deduped and appended AFTER evidence within remaining budget.
        graph_blocks: list[str] = []
        seen_graph: set[str] = set()
        if not scoped:
            for r in results:
                gctx = r.get("graph_context", "")
                if gctx and gctx not in seen_graph:
                    seen_graph.add(gctx)
                    graph_blocks.append(
                        neutralize_evidence_markers(
                            _clip_text(str(gctx), GRAPH_CONTEXT_MAX_CHARS)
                        )
                    )

        graph_text = ""
        if graph_blocks:
            graph_text = "\n---\n[Graph Context]\n" + "\n\n".join(graph_blocks)

        marker_line = format_spatial_application_marker(marker)
        body_budget = max(TOOL_OUTPUT_MAX_CHARS - len(marker_line) - 1, 0)
        header = (
            "[Knowledge Base Evidence for: "
            f"{neutralize_evidence_markers(query)}]\n"
        )
        evidence_budget = body_budget - len(graph_text) - len(header)
        pack, lineage = pack_with_lineage(
            items, budget=max(evidence_budget, 0), preserve_order=True)
        output = header + pack
        if graph_text and len(output) + len(graph_text) <= body_budget:
            output += graph_text
        return _with_qdrant_application(marker, output), lineage
    except Exception as e:
        logger.warning("qdrant_search_failed", error=str(e))
        return _with_qdrant_application(
            _qdrant_marker(
                runtime.state,
                status="failed",
                completeness="unknown",
                detail_code=(
                    "spatial-scope-filter-unavailable"
                    if scoped
                    else "qdrant-search-failed"
                ),
            ),
            (
                "SPATIAL_SCOPE_FILTER_UNAVAILABLE: "
                f"{neutralize_evidence_markers(str(e))}"
                if scoped
                else "Knowledge base search failed: "
                f"{neutralize_evidence_markers(str(e))}"
            ),
        ), []
