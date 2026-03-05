"""LangGraph agent state definition."""

from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """State shared between all agents in the intelligence pipeline."""

    query: str
    messages: Annotated[list[BaseMessage], add_messages]
    osint_results: list[dict[str, str]]
    analysis: str
    synthesis: str
    sources_used: list[str]
    confidence: float
    threat_assessment: str
    agent_chain: list[str]
    iteration: int
    error: str | None
