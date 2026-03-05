"""LangGraph node functions for the intelligence pipeline."""

import structlog
from langchain_core.messages import HumanMessage

from agents.analyst_agent import create_analyst_llm, get_system_message as analyst_sys
from agents.osint_agent import create_osint_llm, get_system_message as osint_sys
from agents.synthesis_agent import create_synthesis_llm, get_system_message as synthesis_sys
from graph.state import AgentState

logger = structlog.get_logger()


async def osint_node(state: AgentState) -> dict:
    """OSINT agent gathers information from available sources."""
    logger.info("osint_node_started", query=state["query"])

    try:
        llm = create_osint_llm()
        messages = [
            osint_sys(),
            HumanMessage(
                content=f"Gather OSINT information about: {state['query']}\n\n"
                "Use your knowledge to provide relevant intelligence findings. "
                "Focus on recent events, key actors, and geopolitical context."
            ),
        ]
        response = await llm.ainvoke(messages)
        content = response.content if isinstance(response.content, str) else str(response.content)

        return {
            "osint_results": [{"source": "llm_analysis", "content": content}],
            "sources_used": ["llm_knowledge"],
            "agent_chain": state.get("agent_chain", []) + ["osint_agent"],
            "messages": [response],
            "iteration": state.get("iteration", 0) + 1,
        }
    except Exception as e:
        logger.error("osint_node_failed", error=str(e))
        return {
            "error": f"OSINT agent failed: {e}",
            "agent_chain": state.get("agent_chain", []) + ["osint_agent"],
            "osint_results": [],
            "iteration": state.get("iteration", 0) + 1,
        }


async def analyst_node(state: AgentState) -> dict:
    """Analyst agent analyzes OSINT results."""
    logger.info("analyst_node_started")

    try:
        osint_text = "\n".join(
            r.get("content", "") for r in state.get("osint_results", [])
        )

        llm = create_analyst_llm()
        messages = [
            analyst_sys(),
            HumanMessage(
                content=f"Analyze the following OSINT findings about: {state['query']}\n\n"
                f"OSINT Data:\n{osint_text}\n\n"
                "Provide a threat assessment (CRITICAL/HIGH/ELEVATED/MODERATE) "
                "and detailed analysis."
            ),
        ]
        response = await llm.ainvoke(messages)
        content = response.content if isinstance(response.content, str) else str(response.content)

        # Extract threat level from response
        threat = "MODERATE"
        for level in ["CRITICAL", "HIGH", "ELEVATED"]:
            if level in content.upper():
                threat = level
                break

        return {
            "analysis": content,
            "threat_assessment": threat,
            "agent_chain": state.get("agent_chain", []) + ["analyst_agent"],
            "messages": [response],
        }
    except Exception as e:
        logger.error("analyst_node_failed", error=str(e))
        return {
            "analysis": f"Analysis failed: {e}",
            "threat_assessment": "MODERATE",
            "error": f"Analyst agent failed: {e}",
            "agent_chain": state.get("agent_chain", []) + ["analyst_agent"],
        }


async def synthesis_node(state: AgentState) -> dict:
    """Synthesis agent produces final intelligence report."""
    logger.info("synthesis_node_started")

    try:
        llm = create_synthesis_llm()
        messages = [
            synthesis_sys(),
            HumanMessage(
                content=f"Synthesize a final intelligence report.\n\n"
                f"Query: {state['query']}\n\n"
                f"Analysis:\n{state.get('analysis', 'No analysis available')}\n\n"
                f"Threat Assessment: {state.get('threat_assessment', 'MODERATE')}\n\n"
                "Produce a concise, actionable intelligence report."
            ),
        ]
        response = await llm.ainvoke(messages)
        content = response.content if isinstance(response.content, str) else str(response.content)

        # Extract confidence from content or default
        confidence = 0.5
        if "high confidence" in content.lower():
            confidence = 0.8
        elif "moderate confidence" in content.lower():
            confidence = 0.6
        elif "low confidence" in content.lower():
            confidence = 0.3

        return {
            "synthesis": content,
            "confidence": confidence,
            "agent_chain": state.get("agent_chain", []) + ["synthesis_agent"],
            "messages": [response],
        }
    except Exception as e:
        logger.error("synthesis_node_failed", error=str(e))
        return {
            "synthesis": f"Synthesis failed: {e}",
            "confidence": 0.0,
            "error": f"Synthesis agent failed: {e}",
            "agent_chain": state.get("agent_chain", []) + ["synthesis_agent"],
        }


def router_node(state: AgentState) -> str:
    """Route to next node based on state. Returns 'continue' or 'more_research'."""
    iteration = state.get("iteration", 0)
    osint_results = state.get("osint_results", [])

    # If we have no results and haven't tried too many times, research more
    if not osint_results and iteration < 2:
        return "more_research"

    return "continue"
