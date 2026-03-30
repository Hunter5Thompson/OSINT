"""LangGraph agent state definition."""

from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """State shared between all agents in the intelligence pipeline."""

    # Input
    query: str
    image_url: str | None

    # ReAct loop
    messages: Annotated[list[BaseMessage], add_messages]
    tool_calls_count: int
    iteration: int

    # Legacy pipeline (kept for fallback)
    osint_results: list[dict[str, str]]
    analysis: str

    # Output (populated by Synthesis)
    synthesis: str
    executive_summary: str
    key_findings: list[str]
    threat_assessment: str
    confidence: float
    sources_used: list[str]
    agent_chain: list[str]
    tool_trace: list[dict]
    error: str | None
