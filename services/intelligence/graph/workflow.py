"""LangGraph workflow definition for the intelligence pipeline."""

import asyncio
from datetime import datetime, timezone

import structlog
from langgraph.graph import END, StateGraph

from graph.nodes import analyst_node, osint_node, router_node, synthesis_node
from graph.state import AgentState

logger = structlog.get_logger()


def build_graph() -> StateGraph:
    """Build the intelligence pipeline graph."""
    graph = StateGraph(AgentState)

    # Add nodes
    graph.add_node("osint", osint_node)
    graph.add_node("analyst", analyst_node)
    graph.add_node("synthesis", synthesis_node)

    # Define edges
    graph.set_entry_point("osint")
    graph.add_conditional_edges(
        "osint",
        router_node,
        {
            "more_research": "osint",
            "continue": "analyst",
        },
    )
    graph.add_edge("analyst", "synthesis")
    graph.add_edge("synthesis", END)

    return graph


# Compile the graph
intelligence_graph = build_graph().compile()


async def run_intelligence_query(query: str, region: str | None = None) -> dict:
    """Run a full intelligence analysis pipeline.

    Args:
        query: The intelligence query.
        region: Optional region filter.

    Returns:
        Dictionary with analysis results.
    """
    logger.info("intelligence_query_started", query=query, region=region)

    initial_state: AgentState = {
        "query": query,
        "messages": [],
        "osint_results": [],
        "analysis": "",
        "synthesis": "",
        "sources_used": [],
        "confidence": 0.0,
        "threat_assessment": "",
        "agent_chain": [],
        "iteration": 0,
        "error": None,
    }

    result = await intelligence_graph.ainvoke(initial_state)

    return {
        "query": query,
        "agent_chain": result.get("agent_chain", []),
        "sources_used": result.get("sources_used", []),
        "analysis": result.get("synthesis", result.get("analysis", "")),
        "confidence": result.get("confidence", 0.0),
        "threat_assessment": result.get("threat_assessment", "MODERATE"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    # Test the workflow
    async def main() -> None:
        result = await run_intelligence_query(
            "Current situation in the Taiwan Strait"
        )
        print(f"Query: {result['query']}")
        print(f"Agent Chain: {' → '.join(result['agent_chain'])}")
        print(f"Threat: {result['threat_assessment']}")
        print(f"Confidence: {result['confidence']}")
        print(f"\nAnalysis:\n{result['analysis']}")

    asyncio.run(main())
