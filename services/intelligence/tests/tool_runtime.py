"""Helpers for invoking runtime-injected tools without exposing runtime to the model."""

from __future__ import annotations

from typing import Any

from langgraph.prebuilt import ToolRuntime

from graph.state import AgentState
from spatial import RetrievalSpatialRelation


def agent_state(**overrides: object) -> AgentState:
    state: AgentState = {
        "query": "test",
        "image_url": None,
        "spatial_scope": None,
        "spatial_relation": RetrievalSpatialRelation.EITHER,
        "grounding_context": "",
        "grounding_evidence_pack": "",
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
    state.update(overrides)  # type: ignore[typeddict-item]
    return state


async def invoke_runtime_tool(
    tool: Any,
    arguments: dict[str, object],
    *,
    state: AgentState | None = None,
) -> str:
    coroutine = tool.coroutine
    assert coroutine is not None
    runtime = ToolRuntime(
        state=state or agent_state(),
        context={},
        config={},
        stream_writer=lambda _chunk: None,
        tool_call_id="test-call",
        store=None,
    )
    result = await coroutine(**arguments, runtime=runtime)
    if isinstance(result, tuple):
        content, _artifact = result
        return content
    return result
