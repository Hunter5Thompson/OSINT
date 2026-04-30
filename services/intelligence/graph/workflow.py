"""LangGraph workflow — ReAct agent + deterministic synthesis with legacy fallback."""

import asyncio
from datetime import datetime, timezone

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from config import settings
from agents.react_agent import (
    REACT_SYSTEM_PROMPT,
    create_react_agent,
    should_continue,
)
from agents.tools import ALL_TOOLS
from agents.tools.graph_query import set_graph_client
from agents.synthesis_agent import create_synthesis_llm, get_system_message as synthesis_sys
from graph.client import GraphClient
from graph.nodes import analyst_node, osint_node, router_node, synthesis_node as legacy_synthesis_node
from graph.state import AgentState

logger = structlog.get_logger()

TOOL_MESSAGE_MAX_CHARS = 2500
REACT_TOOL_HISTORY_MAX_CHARS = 12000
SYNTHESIS_RESEARCH_MAX_CHARS = 18000


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


# ── ReAct Node Functions ──────────────────────────────────────────────────────

async def react_agent_node(state: AgentState) -> dict:
    """ReAct agent node — invokes LLM with tools bound."""
    logger.info("react_agent_node", iteration=state.get("iteration", 0))

    try:
        llm = create_react_agent()

        # Build messages for LLM invocation
        if state.get("iteration", 0) == 0:
            query = state["query"]
            image_note = ""
            if state.get("image_url"):
                image_note = f"\n\nAn image has been provided for analysis: {state['image_url']}"

            initial_messages = [
                SystemMessage(content=REACT_SYSTEM_PROMPT),
                HumanMessage(content=f"{query}{image_note}"),
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

    try:
        llm = create_synthesis_llm()

        # Collect all tool results from messages + derive sources_used from trace
        tool_results = []
        for msg in state.get("messages", []):
            if hasattr(msg, "content") and getattr(msg, "type", None) == "tool":
                tool_results.append(msg.content if isinstance(msg.content, str) else str(msg.content))

        research_text = "\n\n---\n\n".join(tool_results) if tool_results else "No research results collected."
        raw_research_chars = len(research_text)
        research_text = _clip_text(research_text, SYNTHESIS_RESEARCH_MAX_CHARS)

        # Derive sources_used from tool_trace (de-duplicated tool names)
        derived_sources = sorted({entry.get("tool", "?") for entry in state.get("tool_trace", [])})
        logger.info(
            "react_synthesis_grounding",
            tool_call_count=len(state.get("tool_trace", [])),
            unique_tools=derived_sources,
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
        }

    except Exception as e:
        logger.error("react_synthesis_failed", error=str(e))
        return {
            "synthesis": f"Synthesis failed: {e}",
            "threat_assessment": "MODERATE",
            "confidence": 0.0,
            "error": f"Synthesis failed: {e}",
            "agent_chain": state.get("agent_chain", []) + ["synthesis"],
        }


# ── Graph Builders ────────────────────────────────────────────────────────────

def build_react_graph() -> StateGraph:
    """Build the ReAct agent workflow."""
    graph = StateGraph(AgentState)

    graph.add_node("react_agent", react_agent_node)
    graph.add_node("tools", ToolNode(ALL_TOOLS))
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
        _graph_client = GraphClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
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
) -> dict:
    """Run intelligence analysis — ReAct by default, legacy as fallback."""
    mode = "legacy" if use_legacy else "react"
    logger.info("intelligence_query_started", query=query, region=region, mode=mode)

    # Wire Neo4j client for graph_query tool (lazy singleton)
    _ensure_graph_client()

    initial_state: AgentState = {
        "query": query,
        "image_url": image_url,
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
    }

    try:
        if use_legacy:
            result = await legacy_graph.ainvoke(initial_state)
        else:
            result = await asyncio.wait_for(
                react_graph.ainvoke(initial_state),
                timeout=settings.react_total_timeout_s,
            )
    except (asyncio.TimeoutError, Exception) as e:
        if not use_legacy:
            logger.warning("react_fallback_to_legacy", error=str(e))
            try:
                result = await legacy_graph.ainvoke(initial_state)
                mode = "legacy_fallback"
            except Exception as legacy_err:
                logger.error("legacy_fallback_also_failed", error=str(legacy_err))
                return {
                    "query": query,
                    "analysis": f"Both ReAct and legacy pipelines failed: {e} / {legacy_err}",
                    "threat_assessment": "MODERATE",
                    "confidence": 0.0,
                    "sources_used": [],
                    "agent_chain": ["error"],
                    "tool_trace": [],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "mode": "error",
                }
        else:
            return {
                "query": query,
                "analysis": f"Legacy pipeline failed: {e}",
                "threat_assessment": "MODERATE",
                "confidence": 0.0,
                "sources_used": [],
                "agent_chain": ["error"],
                "tool_trace": [],
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "mode": "error",
            }

    return {
        "query": query,
        "agent_chain": result.get("agent_chain", []),
        "sources_used": result.get("sources_used", []),
        "analysis": result.get("synthesis", result.get("analysis", "")),
        "confidence": result.get("confidence", 0.0),
        "threat_assessment": result.get("threat_assessment", "MODERATE"),
        "tool_trace": result.get("tool_trace", []),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
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
