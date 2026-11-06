"""LangGraph agent state definition."""

from typing import Annotated, NotRequired, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

from graph.assessment import AssessmentStatus
from spatial import (
    RetrievalSpatialRelation,
    SpatialRunApplicationV1,
    SpatialScopeTokenV1,
)


class AgentState(TypedDict):
    """State shared between all agents in the intelligence pipeline."""

    # Input
    query: str
    image_url: str | None
    spatial_scope: SpatialScopeTokenV1 | None
    spatial_relation: RetrievalSpatialRelation

    # Deterministic grounding (POSTed by the backend, e.g. country briefing)
    grounding_context: str
    grounding_evidence_pack: str
    # Provenance travels structurally, never via the rendered pack text.
    grounding_evidence_artifact: list[dict]
    notebook_evidence_pack: str
    notebook_evidence_artifact: list[dict]

    research_mode: NotRequired[str]
    current_evidence_pack: NotRequired[str]
    current_evidence_artifact: NotRequired[list[dict]]
    research_coverage: NotRequired[dict | None]

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
    threat_assessment: str | None
    confidence: float | None
    assessment_status: AssessmentStatus | None
    sources_used: list[str]
    evidence_summary: list[dict] | None
    agent_chain: list[str]
    tool_trace: list[dict]
    tool_events: list[dict]
    status: str
    answerability: str
    error: str | None
    spatial_application: SpatialRunApplicationV1 | None
