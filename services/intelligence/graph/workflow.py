"""LangGraph workflow — ReAct agent + deterministic synthesis.

The ReAct path is fail-closed: on failure it propagates (no automatic legacy
fallback). The legacy pipeline runs only when the caller passes use_legacy=True.
"""

import asyncio
from datetime import UTC, datetime

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from agents.react_agent import (
    create_react_agent,
    should_continue,
    system_prompt_for_state,
)
from agents.synthesis_agent import create_synthesis_llm
from agents.synthesis_agent import get_system_message as synthesis_sys
from agents.tools import blocked_tool_names, tools_for_state
from agents.tools.graph_query import set_graph_client
from config import settings
from distill_capture import capture_synthesis_input
from graph.client import GraphClient
from graph.nodes import analyst_node, osint_node, router_node
from graph.nodes import synthesis_node as legacy_synthesis_node
from graph.state import AgentState
from rag.evidence import format_evidence_pack, parse_evidence_refs, to_evidence_item
from spatial import (
    RetrievalSpatialRelation,
    SpatialApplicationMarkerV1,
    SpatialRunApplicationV1,
    SpatialScopeTokenV1,
    aggregate_spatial_application,
    parse_spatial_application_marker,
)

logger = structlog.get_logger()

TOOL_MESSAGE_MAX_CHARS = 2500
REACT_TOOL_HISTORY_MAX_CHARS = 12000
SYNTHESIS_RESEARCH_MAX_CHARS = 18000
GROUNDING_EVIDENCE_MAX_CHARS = 3000


def _clip_text(text: str, max_chars: int) -> str:
    """Bound prompt material before it is sent to the 16k-context local model."""
    if len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    return text[:max_chars].rstrip() + f"\n...[truncated {omitted} chars]"


def _with_content(message, content: str):  # type: ignore[no-untyped-def]
    """Return a copy of a LangChain message with replacement content."""
    if hasattr(message, "model_copy"):
        return message.model_copy(update={"content": content})
    if hasattr(message, "copy"):
        return message.copy(update={"content": content})
    return message


def _compact_tool_messages(messages: list) -> list:  # type: ignore[type-arg]
    """Trim tool-result payloads while preserving message order and tool IDs.

    ReAct loops resend the full conversation after each tool call. Keeping the
    newest tool outputs first gives Munin the freshest evidence while preventing
    older retrieval dumps from consuming the whole prompt window.
    """
    remaining = REACT_TOOL_HISTORY_MAX_CHARS
    compacted_reversed = []

    for message in reversed(messages):
        if getattr(message, "type", None) != "tool":
            compacted_reversed.append(message)
            continue

        content = message.content if isinstance(message.content, str) else str(message.content)
        if remaining <= 0:
            next_content = "[tool output omitted: context budget exhausted]"
        else:
            next_content = _clip_text(content, min(TOOL_MESSAGE_MAX_CHARS, remaining))
            remaining -= len(next_content)
        compacted_reversed.append(_with_content(message, next_content))

    return list(reversed(compacted_reversed))


def derive_sources_used(tool_outputs: list[str]) -> list[str]:
    """Deduplicated provider IDs in first-seen (evidence) order.

    Parses [EVIDENCE] <json> blocks. Never falls back to tool names or
    "llm_knowledge". Empty list if there is no real evidence lineage.
    """
    seen: set[str] = set()
    ordered: list[str] = []
    for out in tool_outputs:
        for ref in parse_evidence_refs(out):
            if ref.provider not in seen:
                seen.add(ref.provider)
                ordered.append(ref.provider)
    return ordered


# ── ReAct Node Functions ──────────────────────────────────────────────────────

async def react_agent_node(state: AgentState) -> dict:
    """ReAct agent node — invokes LLM with tools bound."""
    logger.info("react_agent_node", iteration=state.get("iteration", 0))

    try:
        llm = create_react_agent(tools_for_state(state))

        # Build messages for LLM invocation
        if state.get("iteration", 0) == 0:
            query = state["query"]
            image_note = ""
            if state.get("image_url"):
                image_note = "\n\nAn attached image is available through the vision tool."

            scope = state.get("spatial_scope")
            scope_note = (
                f"\n\nActive server-pinned scope: {scope.scope_key} "
                f"({state['spatial_relation'].value})."
                if scope is not None
                else "\n\nActive server-pinned scope: global."
            )

            grounding = state.get("grounding_context") or ""
            grounding_note = f"\n\n{grounding}" if grounding else ""

            initial_messages = [
                SystemMessage(content=system_prompt_for_state(state)),
                HumanMessage(content=f"{query}{image_note}{scope_note}{grounding_note}"),
            ]
            messages = list(state.get("messages", [])) + initial_messages
        else:
            messages = _compact_tool_messages(list(state.get("messages", [])))
            # Qwen3.5 chat template requires a user message after tool results.
            # Without this, the template raises "No user query found in messages".
            messages.append(
                HumanMessage(content="Continue your analysis based on the tool results above.")
            )

        response = await llm.ainvoke(messages)

        # Count tool calls in this response
        tool_calls = getattr(response, "tool_calls", None) or []
        new_tool_calls = len(tool_calls)

        # Populate tool_trace for transparency in the final analysis
        new_trace_entries = [
            {
                "iteration": state.get("iteration", 0),
                "tool": tc.get("name", "?"),
                "args": tc.get("args", {}),
            }
            for tc in tool_calls
        ]

        logger.info(
            "react_agent_invoked",
            iteration=state.get("iteration", 0),
            tool_calls_in_response=new_tool_calls,
            tools=[tc.get("name") for tc in tool_calls],
        )

        return {
            "messages": [response],
            "iteration": state.get("iteration", 0) + 1,
            "tool_calls_count": state.get("tool_calls_count", 0) + new_tool_calls,
            "agent_chain": state.get("agent_chain", []) + ["react_agent"],
            "tool_trace": state.get("tool_trace", []) + new_trace_entries,
        }

    except Exception as e:
        logger.error("react_agent_failed", error=str(e))
        return {
            "error": f"ReAct agent failed: {e}",
            "agent_chain": state.get("agent_chain", []) + ["react_agent"],
            "iteration": state.get("iteration", 0) + 1,
        }


async def react_synthesis_node(state: AgentState) -> dict:
    """Deterministic synthesis node — produces structured intelligence report."""
    logger.info("react_synthesis_node")

    spatial_application: SpatialRunApplicationV1 | None = None
    try:
        llm = create_synthesis_llm()

        # Collect all tool results from messages + derive sources_used from trace
        tool_results: list[str] = []
        application_markers: list[SpatialApplicationMarkerV1] = []
        for msg in state.get("messages", []):
            if hasattr(msg, "content") and getattr(msg, "type", None) == "tool":
                content = msg.content if isinstance(msg.content, str) else str(msg.content)
                marker, research_text = parse_spatial_application_marker(
                    content,
                    actual_tool_name=getattr(msg, "name", None),
                )
                if marker is not None:
                    application_markers.append(marker)
                if research_text:
                    tool_results.append(research_text)

        scope = state.get("spatial_scope")
        if scope is not None:
            application = aggregate_spatial_application(
                scope,
                state["spatial_relation"],
                application_markers,
                blocked_tools=blocked_tool_names(state),
            )
            spatial_application = application

        # Prepend the deterministic grounding pack so it is part of the synthesis
        # research text AND counted first by derive_sources_used (sources_used).
        pack = state.get("grounding_evidence_pack") or ""
        tool_results = ([pack] if pack else []) + tool_results

        research_text = (
            "\n\n---\n\n".join(tool_results)
            if tool_results
            else "No research results collected."
        )
        raw_research_chars = len(research_text)
        research_text = _clip_text(research_text, SYNTHESIS_RESEARCH_MAX_CHARS)

        # Derive sources_used from parsed [EVIDENCE] blocks (de-duplicated provider IDs)
        derived_sources = derive_sources_used(tool_results)
        logger.info(
            "react_synthesis_grounding",
            tool_call_count=len(state.get("tool_trace", [])),
            providers=derived_sources,
            tool_message_count=len(tool_results),
            raw_research_chars=raw_research_chars,
            research_chars=len(research_text),
        )

        messages = [
            synthesis_sys(),
            HumanMessage(
                content=(
                    f"Erstelle einen finalen Intelligence-Lagebericht auf Deutsch.\n\n"
                    f"Anfrage: {state['query']}\n\n"
                    f"Recherche-Ergebnisse:\n{research_text}\n\n"
                    "Liefere einen knappen, handlungsrelevanten Report auf Deutsch mit:\n"
                    "1. Executive Summary (2–3 Sätze)\n"
                    "2. Key Findings (Bulletpoints)\n"
                    "3. Threat Assessment — genau eines von: "
                    "CRITICAL / HIGH / ELEVATED / MODERATE (Label englisch, "
                    "Begründung deutsch)\n"
                    "4. Confidence Level — genau einer der Strings "
                    "\"high confidence\", \"moderate confidence\" oder "
                    "\"low confidence\" im Text (Begründung deutsch)\n"
                    "5. Recommended Actions"
                ),
            ),
        ]
        capture_synthesis_input(state["query"], messages)  # no-op unless DISTILL_CAPTURE_DIR set
        response = await llm.ainvoke(messages)
        content = response.content if isinstance(response.content, str) else str(response.content)

        # Extract threat level
        threat = "MODERATE"
        for level in ["CRITICAL", "HIGH", "ELEVATED"]:
            if level in content.upper():
                threat = level
                break

        # Extract confidence
        confidence = 0.5
        if "high confidence" in content.lower():
            confidence = 0.8
        elif "moderate confidence" in content.lower():
            confidence = 0.6
        elif "low confidence" in content.lower():
            confidence = 0.3

        return {
            "synthesis": content,
            "threat_assessment": threat,
            "confidence": confidence,
            "sources_used": derived_sources,
            "agent_chain": state.get("agent_chain", []) + ["synthesis"],
            "messages": [response],
            "spatial_application": spatial_application,
        }

    except Exception as e:
        logger.error("react_synthesis_failed", error=str(e))
        return {
            "synthesis": f"Synthesis failed: {e}",
            "threat_assessment": "MODERATE",
            "confidence": 0.0,
            "error": f"Synthesis failed: {e}",
            "agent_chain": state.get("agent_chain", []) + ["synthesis"],
            "spatial_application": spatial_application,
        }


# ── Graph Builders ────────────────────────────────────────────────────────────

async def tool_node_for_state(state: AgentState) -> dict:
    """Execute only the same closed capability set exposed to the model."""

    result = await ToolNode(tools_for_state(state)).ainvoke(state)
    return dict(result)


def build_react_graph() -> StateGraph:
    """Build the ReAct agent workflow."""
    graph = StateGraph(AgentState)

    graph.add_node("react_agent", react_agent_node)
    graph.add_node("tools", tool_node_for_state)
    graph.add_node("synthesis", react_synthesis_node)

    graph.set_entry_point("react_agent")
    graph.add_conditional_edges(
        "react_agent",
        should_continue,
        {
            "tools": "tools",
            "synthesis": "synthesis",
        },
    )
    graph.add_edge("tools", "react_agent")
    graph.add_edge("synthesis", END)

    return graph


def build_legacy_graph() -> StateGraph:
    """Build the legacy linear pipeline (fallback)."""
    graph = StateGraph(AgentState)

    graph.add_node("osint", osint_node)
    graph.add_node("analyst", analyst_node)
    graph.add_node("synthesis", legacy_synthesis_node)

    graph.set_entry_point("osint")
    graph.add_conditional_edges(
        "osint",
        router_node,
        {"more_research": "osint", "continue": "analyst"},
    )
    graph.add_edge("analyst", "synthesis")
    graph.add_edge("synthesis", END)

    return graph


# Compile both graphs
react_graph = build_react_graph().compile()
legacy_graph = build_legacy_graph().compile()

# ── Neo4j Lifecycle (lazy singleton) ──────────────────────────────────────────

_graph_client: GraphClient | None = None


def _ensure_graph_client() -> None:
    """Initialize the shared GraphClient singleton on first use."""
    global _graph_client
    if _graph_client is not None:
        return
    from config import settings
    try:
        _graph_client = GraphClient(
            settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password
        )
        set_graph_client(_graph_client)
        logger.info("graph_client_initialized")
    except Exception as e:
        logger.warning("graph_client_init_failed", error=str(e))


async def shutdown_graph_client() -> None:
    """Close the shared GraphClient. Call from FastAPI shutdown / atexit."""
    global _graph_client
    if _graph_client is not None:
        await _graph_client.close()
        _graph_client = None
        set_graph_client(None)
        logger.info("graph_client_closed")


async def run_intelligence_query(
    query: str,
    region: str | None = None,
    image_url: str | None = None,
    use_legacy: bool = False,
    *,
    spatial_scope: SpatialScopeTokenV1 | None = None,
    spatial_relation: RetrievalSpatialRelation = RetrievalSpatialRelation.EITHER,
    grounding_context: str | None = None,
    grounding_evidence: list[dict] | None = None,
) -> dict:
    """Run intelligence analysis — ReAct by default (fail-closed on failure);
    the legacy pipeline runs only when use_legacy=True."""
    mode = "legacy" if use_legacy else "react"
    pinned_scope = spatial_scope.model_copy(deep=True) if spatial_scope is not None else None
    pinned_relation = RetrievalSpatialRelation(spatial_relation)
    logger.info(
        "intelligence_query_started",
        scope_key=pinned_scope.scope_key if pinned_scope is not None else "world",
        catalog_revision=(
            pinned_scope.catalog_revision if pinned_scope is not None else None
        ),
        mode=mode,
        deprecated_region_supplied=region is not None,
    )

    # Wire Neo4j client for graph_query tool (lazy singleton)
    _ensure_graph_client()

    items = [to_evidence_item(d) for d in (grounding_evidence or [])]
    grounding_evidence_pack = (
        format_evidence_pack(items, budget=GROUNDING_EVIDENCE_MAX_CHARS) if items else ""
    )

    initial_state: AgentState = {
        "query": query,
        "image_url": image_url,
        "spatial_scope": pinned_scope,
        "spatial_relation": pinned_relation,
        "grounding_context": grounding_context or "",
        "grounding_evidence_pack": grounding_evidence_pack,
        "messages": [],
        "tool_calls_count": 0,
        "iteration": 0,
        "osint_results": [],
        "analysis": "",
        "synthesis": "",
        "executive_summary": "",
        "key_findings": [],
        "threat_assessment": "",
        "confidence": 0.0,
        "sources_used": [],
        "agent_chain": [],
        "tool_trace": [],
        "error": None,
        "spatial_application": None,
    }

    try:
        if use_legacy:
            result = await legacy_graph.ainvoke(initial_state)
        else:
            result = await asyncio.wait_for(
                react_graph.ainvoke(initial_state),
                timeout=settings.react_total_timeout_s,
            )
    except (TimeoutError, Exception) as e:
        if not use_legacy:
            # Fail closed: a ReAct failure must surface to the backend as a
            # non-2xx (FastAPI 500). Never silently fall back to the legacy
            # (no-sources) pipeline or return a mode:"error" HTTP-200 dict —
            # that would let an analyst receive a degraded report believing it
            # was a real analysis (Phase 4 / C7).
            logger.error("react_pipeline_failed", error=str(e))
            raise
        logger.error("legacy_pipeline_failed", error=str(e))
        return {
            "query": query,
            "analysis": f"Legacy pipeline failed: {e}",
            "threat_assessment": "MODERATE",
            "confidence": 0.0,
            "sources_used": [],
            "agent_chain": ["error"],
            "tool_trace": [],
            "timestamp": datetime.now(UTC).isoformat(),
            "mode": "error",
            "spatial_scope": (
                pinned_scope.model_dump(mode="json") if pinned_scope is not None else None
            ),
            "spatial_relation": pinned_relation.value,
            "spatial_application": None,
        }

    result_application = result.get("spatial_application")
    serialized_application = (
        result_application.model_dump(mode="json")
        if isinstance(result_application, SpatialRunApplicationV1)
        else result_application
    )
    return {
        "query": query,
        "agent_chain": result.get("agent_chain", []),
        "sources_used": result.get("sources_used", []),
        "analysis": result.get("synthesis", result.get("analysis", "")),
        "confidence": result.get("confidence", 0.0),
        "threat_assessment": result.get("threat_assessment", "MODERATE"),
        "tool_trace": result.get("tool_trace", []),
        "timestamp": datetime.now(UTC).isoformat(),
        "mode": mode,
        "spatial_scope": (
            pinned_scope.model_dump(mode="json") if pinned_scope is not None else None
        ),
        "spatial_relation": pinned_relation.value,
        "spatial_application": serialized_application,
    }


if __name__ == "__main__":
    async def main() -> None:
        result = await run_intelligence_query(
            "Current situation in the Taiwan Strait"
        )
        print(f"Query: {result['query']}")
        print(f"Mode: {result['mode']}")
        print(f"Agent Chain: {' → '.join(result['agent_chain'])}")
        print(f"Threat: {result['threat_assessment']}")
        print(f"Confidence: {result['confidence']}")
        print(f"\nAnalysis:\n{result['analysis']}")

    asyncio.run(main())
