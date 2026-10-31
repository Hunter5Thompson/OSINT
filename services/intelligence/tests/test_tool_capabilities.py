"""Closed capability binding for global and spatially scoped ReAct runs."""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, StateGraph

from agents.tools import blocked_tool_names, tools_for_state
from graph.state import AgentState
from spatial import ScopeKind, SpatialScopeTokenV1
from tests.tool_runtime import agent_state


def _scope_token(kind: ScopeKind = ScopeKind.COUNTRY) -> SpatialScopeTokenV1:
    scope_key = {
        ScopeKind.WORLD: "world",
        ScopeKind.COUNTRY: "country:UKR",
        ScopeKind.ADMIN1: "admin1:iso3166-2:UA-30",
        ScopeKind.ADMIN2: "admin2:geonames:703448",
    }[kind]
    revision = "spatial-derive-v1-d30efa07e141"
    return SpatialScopeTokenV1(
        scope_key=scope_key,
        kind=kind,
        catalog_revision="spatial-v1-e76a16bff799",
        derivation_revision=revision,
        boundary_policy="odin-reference-v1",
        compatible_derivation_revisions=(revision,),
    )


def _names(tools: Sequence[BaseTool]) -> list[str]:
    return [tool.name for tool in tools]


def test_scoped_binding_excludes_unscoped_sources_and_image_without_attachment() -> None:
    state = agent_state(spatial_scope=_scope_token())

    assert _names(tools_for_state(state)) == [
        "qdrant_search",
        "query_knowledge_graph",
        "classify_event",
    ]
    assert blocked_tool_names(state) == (
        "analyze_image",
        "gdelt_query",
        "rss_fetch",
    )


def test_scoped_binding_adds_vision_only_for_the_attached_image() -> None:
    state = agent_state(
        spatial_scope=_scope_token(),
        image_url="https://example.test/attached.png",
    )

    assert _names(tools_for_state(state)) == [
        "qdrant_search",
        "query_knowledge_graph",
        "classify_event",
        "analyze_image",
    ]
    assert blocked_tool_names(state) == ("gdelt_query", "rss_fetch")


@pytest.mark.parametrize("scope", [None, _scope_token(ScopeKind.WORLD)])
def test_global_binding_retains_approved_capabilities(
    scope: SpatialScopeTokenV1 | None,
) -> None:
    state = agent_state(spatial_scope=scope)

    assert _names(tools_for_state(state)) == [
        "qdrant_search",
        "query_knowledge_graph",
        "classify_event",
        "gdelt_query",
        "rss_fetch",
    ]
    assert blocked_tool_names(state) == ("analyze_image",)


@pytest.mark.asyncio
async def test_react_node_binds_exactly_the_state_capabilities(monkeypatch) -> None:
    import graph.workflow as workflow

    captured: dict[str, list[str]] = {}

    class FakeReact:
        async def ainvoke(self, _messages: list[object]) -> AIMessage:
            return AIMessage(content="done")

    def fake_create_react_agent(tools: list[BaseTool]) -> FakeReact:
        captured["tools"] = _names(tools)
        return FakeReact()

    monkeypatch.setattr(workflow, "create_react_agent", fake_create_react_agent)

    await workflow.react_agent_node(agent_state(spatial_scope=_scope_token()))

    assert captured["tools"] == [
        "qdrant_search",
        "query_knowledge_graph",
        "classify_event",
    ]


@pytest.mark.asyncio
async def test_tool_node_is_built_from_the_same_state_capabilities(monkeypatch) -> None:
    import graph.workflow as workflow

    captured: dict[str, list[str]] = {}

    real_tool_node = workflow.ToolNode

    def recording_tool_node(tools: list[BaseTool], *, awrap_tool_call, handle_tool_errors):
        captured["tools"] = _names(tools)
        return real_tool_node(
            tools, awrap_tool_call=awrap_tool_call, handle_tool_errors=handle_tool_errors,
        )

    monkeypatch.setattr(workflow, "ToolNode", recording_tool_node)
    state = agent_state(
        spatial_scope=_scope_token(), messages=[AIMessage(content="No tool calls")],
    )

    graph = StateGraph(AgentState)
    graph.add_node("tools", workflow.tool_node_for_state)
    graph.set_entry_point("tools")
    graph.add_edge("tools", END)
    await graph.compile().ainvoke(state)

    assert captured["tools"] == [
        "qdrant_search",
        "query_knowledge_graph",
        "classify_event",
    ]
