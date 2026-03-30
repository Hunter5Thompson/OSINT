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


# ── ReAct Node Functions ──────────────────────────────────────────────────────

async def react_agent_node(state: AgentState) -> dict:
    """ReAct agent node — invokes LLM with tools bound."""
    logger.info("react_agent_node", iteration=state.get("iteration", 0))

    try:
        llm = create_react_agent()

        # Build initial messages if first iteration
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
            messages = list(state.get("messages", []))

        response = await llm.ainvoke(messages)

        # Count tool calls in this response
        new_tool_calls = len(response.tool_calls) if hasattr(response, "tool_calls") else 0

        return {
            "messages": [response],
            "iteration": state.get("iteration", 0) + 1,
            "tool_calls_count": state.get("tool_calls_count", 0) + new_tool_calls,
            "agent_chain": state.get("agent_chain", []) + ["react_agent"],
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

        # Collect all tool results from messages
        tool_results = []
        for msg in state.get("messages", []):
            if hasattr(msg, "content") and getattr(msg, "type", None) == "tool":
                tool_results.append(msg.content if isinstance(msg.content, str) else str(msg.content))

        research_text = "\n\n---\n\n".join(tool_results) if tool_results else "No research results collected."

        messages = [
            synthesis_sys(),
            HumanMessage(
                content=(
                    f"Synthesize a final intelligence report.\n\n"
                    f"Query: {state['query']}\n\n"
                    f"Research Findings:\n{research_text}\n\n"
                    "Produce a concise, actionable intelligence report with:\n"
                    "1. Executive Summary (2-3 sentences)\n"
                    "2. Key Findings (bullet list)\n"
                    "3. Threat Assessment (CRITICAL/HIGH/ELEVATED/MODERATE)\n"
                    "4. Confidence Level (high/moderate/low)\n"
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
