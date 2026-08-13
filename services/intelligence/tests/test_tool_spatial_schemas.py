"""Model-visible tool schemas must not expose trusted runtime inputs."""

import pytest

from agents.tools import ALL_TOOLS, tools_for_state
from agents.tools.graph_query import query_knowledge_graph
from agents.tools.qdrant_search import qdrant_search
from agents.tools.vision import analyze_image
from spatial import RetrievalSpatialRelation, ScopeKind, SpatialScopeTokenV1
from tests.tool_runtime import agent_state, invoke_runtime_tool

_SCOPED_GRAPH_TEMPLATES = (
    "event_timeline",
    "events_by_entity",
    "co_occurring",
    "source_backed",
)
_GLOBAL_ONLY_GRAPH_TEMPLATES = (
    "entity_lookup",
    "one_hop",
    "two_hop_network",
    "top_connected",
)


def _properties(tool) -> set[str]:  # type: ignore[no-untyped-def]
    schema = tool.tool_call_schema.model_json_schema()
    return set(schema.get("properties", {}))


def _graph_tool(tools: list[object]) -> object:
    return next(tool for tool in tools if getattr(tool, "name", None) == "query_knowledge_graph")


def _scope_token() -> SpatialScopeTokenV1:
    revision = "spatial-derive-v1-d30efa07e141"
    return SpatialScopeTokenV1(
        scope_key="country:UKR",
        kind=ScopeKind.COUNTRY,
        catalog_revision="spatial-v1-e76a16bff799",
        derivation_revision=revision,
        boundary_policy="odin-reference-v1",
        compatible_derivation_revisions=(revision,),
    )


def test_retrieval_and_vision_tool_schemas_hide_runtime_controls() -> None:
    assert _properties(qdrant_search) == {"query"}
    assert _properties(query_knowledge_graph) == {"question"}
    assert _properties(analyze_image) == {"question"}

    forbidden = {"scope", "spatial_scope", "spatial_relation", "region", "image_url"}
    for tool in (qdrant_search, query_knowledge_graph, analyze_image):
        assert _properties(tool).isdisjoint(forbidden)


def test_scoped_graph_schema_lists_only_allowlisted_templates() -> None:
    original_description = query_knowledge_graph.description
    scoped = _graph_tool(tools_for_state(agent_state(spatial_scope=_scope_token())))

    assert scoped is not query_knowledge_graph
    assert _properties(scoped) == {"question"}
    schema = scoped.tool_call_schema.model_json_schema()
    visible = f"{scoped.description}\n{schema.get('description', '')}"
    for template in _SCOPED_GRAPH_TEMPLATES:
        assert template in visible
    for template in _GLOBAL_ONLY_GRAPH_TEMPLATES:
        assert template not in visible

    assert query_knowledge_graph.description == original_description
    assert query_knowledge_graph is _graph_tool(ALL_TOOLS)


def test_global_graph_schema_keeps_all_templates() -> None:
    for state in (
        agent_state(),
        agent_state(spatial_scope=SpatialScopeTokenV1(
            scope_key="world",
            kind=ScopeKind.WORLD,
            catalog_revision="spatial-v1-e76a16bff799",
            derivation_revision="spatial-derive-v1-d30efa07e141",
            boundary_policy="odin-reference-v1",
            compatible_derivation_revisions=("spatial-derive-v1-d30efa07e141",),
        )),
    ):
        bound = _graph_tool(tools_for_state(state))
        assert bound is query_knowledge_graph
        for template in (*_SCOPED_GRAPH_TEMPLATES, *_GLOBAL_ONLY_GRAPH_TEMPLATES):
            assert template in bound.description


@pytest.mark.asyncio
async def test_scoped_graph_variant_stays_fail_closed_on_about() -> None:
    scoped = _graph_tool(tools_for_state(agent_state(spatial_scope=_scope_token())))
    result = await invoke_runtime_tool(
        scoped,
        {"question": 'events about "NATO"'},
        state=agent_state(
            spatial_scope=_scope_token(),
            spatial_relation=RetrievalSpatialRelation.ABOUT,
        ),
    )

    assert "SPATIAL_SCOPE_UNSUPPORTED" in result
    assert query_knowledge_graph.description != scoped.description
