"""ReAct research agent — LLM with bind_tools for autonomous tool selection.

Uses Qwen3.5-27B-AWQ via vLLM with LangChain's tool calling interface.
Guard logic enforces max_tool_calls and max_iterations.
"""

from __future__ import annotations

import structlog
from langchain_openai import ChatOpenAI

from agents.tools import ALL_TOOLS
from config import settings
from graph.state import AgentState

log = structlog.get_logger(__name__)

REACT_SYSTEM_PROMPT = f"""\
You are a geopolitical intelligence analyst with access to specialized tools.

Your job is to answer intelligence queries by gathering information from
multiple sources, analyzing patterns, and identifying threats.

Available tools:
- qdrant_search: Search the intelligence knowledge base (Qdrant RAG with reranking + graph context)
- query_knowledge_graph: Query entity relationships and event timelines (Neo4j)
- classify_event: Classify text using the intelligence event codebook
- analyze_image: Analyze images (satellite, documents, maps) — only if image provided
- gdelt_query: Search recent global events via GDELT
- rss_fetch: Fetch articles from RSS feeds

Guidelines:
- Start with qdrant_search or query_knowledge_graph for existing intelligence
- Use gdelt_query for recent/breaking events not yet in the knowledge base
- Use classify_event when you need to categorize an event precisely
- Use analyze_image ONLY when an image URL is provided in the query
- Cross-reference findings from multiple sources when possible
- Stop when you have sufficient evidence — do not use tools unnecessarily
- Maximum {settings.react_max_tool_calls} tool calls allowed
"""


def create_react_agent() -> ChatOpenAI:
    """Create the ReAct agent LLM with tools bound."""
    llm = ChatOpenAI(
        base_url=settings.llm_base_url,
        api_key="not-needed",
        model=settings.llm_model,
        temperature=0.3,
        max_tokens=2000,
    )
    return llm.bind_tools(ALL_TOOLS)


def guard_check(state: AgentState) -> str:
    """Check if ReAct guards have been exceeded. Returns 'continue' or 'stop'."""
    if state.get("tool_calls_count", 0) >= settings.react_max_tool_calls:
        log.warning("react_guard_tool_limit", count=state["tool_calls_count"])
        return "stop"
    if state.get("iteration", 0) >= settings.react_max_iterations:
        log.warning("react_guard_iteration_limit", iteration=state["iteration"])
        return "stop"
    return "continue"


def should_continue(state: AgentState) -> str:
    """Decide whether to execute tools or go to synthesis.
    Returns 'tools' or 'synthesis'.
    """
    if guard_check(state) == "stop":
        return "synthesis"

    messages = state.get("messages", [])
    if not messages:
        return "synthesis"

    last_message = messages[-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"

    return "synthesis"
