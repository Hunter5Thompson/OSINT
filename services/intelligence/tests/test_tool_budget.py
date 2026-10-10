"""L03 counts actual starts at the ToolNode boundary, including failed calls."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, StateGraph

import graph.workflow as workflow
from agents.react_agent import should_continue
from graph.state import AgentState
from rag.evidence import EvidenceItem, SourceRef, evidence_artifact
from tests.tool_runtime import agent_state


def _calls(count):
    return [{"name": "probe", "args": {}, "id": f"call-{index}"} for index in range(count)]


def _tool_graph():
    graph = StateGraph(AgentState)
    graph.add_node("tools", workflow.tool_node_for_state)
    graph.set_entry_point("tools")
    graph.add_edge("tools", END)
    return graph.compile()


def test_fifth_turn_pending_calls_are_not_discarded():
    state = agent_state(
        iteration=5, tool_calls_count=4, messages=[AIMessage(content="", tool_calls=_calls(1))]
    )
    assert should_continue(state) == "tools"


@pytest.mark.parametrize(
    ("used", "batch", "allowed"), [(7, 1, 1), (7, 3, 1), (8, 1, 0), (0, 10, 8)]
)
async def test_batch_reserves_only_remaining_slots(monkeypatch, used, batch, allowed):
    starts = []
    artifact = evidence_artifact(
        [
            EvidenceItem(
                source=SourceRef(
                    source_ref_id="synthetic",
                    source_type="rss",
                    provider="unit.example",
                    display_name=None,
                    url=None,
                    published_at=None,
                    credibility_score=0.8,
                    provenance_inferred=False,
                ),
                title="synthetic",
                excerpt="synthetic",
                relevance_score=0.8,
            ),
        ]
    )

    @tool(response_format="content_and_artifact")
    async def probe():
        """Synthetic evidence provider; record starts before yielding."""
        starts.append("started")
        await asyncio.sleep(0)
        return "synthetic", artifact

    monkeypatch.setattr(workflow, "tools_for_state", lambda state: [probe])
    result = await _tool_graph().ainvoke(
        agent_state(
            tool_calls_count=used,
            iteration=1,
            messages=[AIMessage(content="", tool_calls=_calls(batch))],
        )
    )
    assert len(starts) == allowed
    assert result["tool_calls_count"] == used + allowed
    assert len(result["tool_trace"]) == allowed
    messages = [msg for msg in result["messages"] if isinstance(msg, ToolMessage)]
    assert [msg.tool_call_id for msg in messages] == [f"call-{index}" for index in range(batch)]
    assert all(msg.artifact == artifact for msg in messages[:allowed])
    assert all(msg.status == "error" and not msg.artifact for msg in messages[allowed:])
    assert all("budget" in msg.content.lower() for msg in messages[allowed:])


async def test_proposals_do_not_increment_started_count_or_trace(monkeypatch):
    llm = AsyncMock()
    llm.ainvoke.return_value = AIMessage(content="", tool_calls=_calls(3))
    monkeypatch.setattr(workflow, "create_react_agent", lambda tools: llm)
    result = await workflow.react_agent_node(agent_state(tool_calls_count=7))
    assert result.get("tool_calls_count", 7) == 7
    assert result.get("tool_trace", []) == []


@pytest.mark.parametrize(
    ("used", "iteration", "route"),
    [(7, 4, "react_agent"), (8, 4, "synthesis"), (3, 5, "synthesis")],
)
def test_after_tools_stops_before_exhausted_next_decision(used, iteration, route):
    assert (
        workflow.route_after_tools(agent_state(tool_calls_count=used, iteration=iteration)) == route
    )


async def test_exhausted_iteration_does_not_invoke_llm(monkeypatch):
    llm = AsyncMock()
    monkeypatch.setattr(workflow, "create_react_agent", lambda tools: llm)
    result = await workflow.react_agent_node(agent_state(iteration=5))
    assert result == {}
    llm.ainvoke.assert_not_awaited()


async def test_tool_error_consumes_one_started_slot(monkeypatch):
    starts = []

    @tool
    async def probe():
        """Fail after starting."""
        starts.append(True)
        raise RuntimeError("synthetic provider failure")

    monkeypatch.setattr(workflow, "tools_for_state", lambda state: [probe])
    result = await _tool_graph().ainvoke(
        agent_state(
            tool_calls_count=7,
            iteration=1,
            messages=[AIMessage(content="", tool_calls=_calls(2))],
        )
    )
    assert starts == [True]
    assert result["tool_calls_count"] == 8 and len(result["tool_trace"]) == 1
    messages = [msg for msg in result["messages"] if isinstance(msg, ToolMessage)]
    assert len(messages) == 2 and all(msg.status == "error" for msg in messages)


async def test_fifth_decision_turn_runs_tools_then_synthesizes_without_sixth(monkeypatch):
    starts = []
    decisions = []

    @tool
    async def probe():
        """Synthetic provider."""
        starts.append(True)
        return "synthetic"

    class DecisionLLM:
        async def ainvoke(self, messages):
            decisions.append(True)
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "probe",
                        "args": {},
                        "id": f"turn-{len(decisions)}",
                    }
                ],
            )

    synthesis = AsyncMock()
    synthesis.ainvoke.return_value = AIMessage(
        content="Threat Assessment: MODERATE\nConfidence Level: low confidence",
    )
    monkeypatch.setattr(workflow, "tools_for_state", lambda state: [probe])
    monkeypatch.setattr(workflow, "create_react_agent", lambda tools: DecisionLLM())
    monkeypatch.setattr(workflow, "create_synthesis_llm", lambda: synthesis)
    result = await workflow.build_react_graph().compile().ainvoke(agent_state())
    assert len(decisions) == 5 and len(starts) == 5
    assert result["tool_calls_count"] == 5 and len(result["tool_trace"]) == 5
    synthesis.ainvoke.assert_awaited_once()


async def test_cancelled_batch_does_not_start_blocked_calls(monkeypatch):
    started = asyncio.Event()
    stopped = asyncio.Event()
    starts = []

    @tool
    async def probe():
        """Wait for cancellation at the provider boundary."""
        starts.append(True)
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    monkeypatch.setattr(workflow, "tools_for_state", lambda state: [probe])
    task = asyncio.create_task(
        _tool_graph().ainvoke(
            agent_state(
                tool_calls_count=7,
                iteration=1,
                messages=[AIMessage(content="", tool_calls=_calls(3))],
            )
        )
    )
    await asyncio.wait_for(started.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.wait_for(stopped.wait(), timeout=2)
    assert starts == [True]
