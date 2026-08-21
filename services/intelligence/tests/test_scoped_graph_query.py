"""Fail-closed Neo4j scope templates for non-global Munin runs."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agents.tools.graph_query import query_knowledge_graph, set_graph_client
from agents.tools.graph_templates import SCOPED_TEMPLATES
from spatial import (
    RetrievalSpatialRelation,
    ScopeKind,
    SpatialScopeTokenV1,
    parse_spatial_application_marker,
)
from tests.tool_runtime import agent_state, invoke_runtime_tool

_SCOPE_FIELD = {
    ScopeKind.COUNTRY: "country_scope_key",
    ScopeKind.ADMIN1: "admin1_scope_key",
    ScopeKind.ADMIN2: "admin2_scope_key",
}
_SCOPE_KEY = {
    ScopeKind.COUNTRY: "country:UKR",
    ScopeKind.ADMIN1: "admin1:iso3166-2:UA-14",
    ScopeKind.ADMIN2: "admin2:test:kyiv",
}
_QUESTION = {
    "event_timeline": "timeline of Kyiv",
    "events_by_entity": 'events involving "NATO"',
    "source_backed": 'sources for "NATO"',
    "co_occurring": 'co-occurring entities of "NATO"',
}


def _token(kind: ScopeKind) -> SpatialScopeTokenV1:
    revision = "spatial-derive-v1-d30efa07e141"
    return SpatialScopeTokenV1(
        scope_key=_SCOPE_KEY[kind],
        kind=kind,
        catalog_revision="spatial-v1-e76a16bff799",
        derivation_revision=revision,
        boundary_policy="odin-reference-v1",
        compatible_derivation_revisions=(revision, "spatial-derive-v1-aaaaaaaaaaaa"),
    )


def test_scoped_registry_is_complete_static_and_parameterized() -> None:
    expected = {
        (template_id, kind)
        for template_id in _QUESTION
        for kind in _SCOPE_FIELD
    }
    assert set(SCOPED_TEMPLATES) == expected

    for (template_id, kind), template in SCOPED_TEMPLATES.items():
        cypher = template["cypher"]
        assert "$scope_key" in cypher
        assert "$compatible_revisions" in cypher
        assert f"l.{_SCOPE_FIELD[kind]} = $scope_key" in cypher
        assert "l.spatial_conflict = false" in cypher
        assert "coalesce(l.spatial_conflict" not in cypher
        assert "DISTINCT" in cypher, template_id
        assert "{" not in cypher and "}" not in cypher


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", list(_SCOPE_FIELD))
@pytest.mark.parametrize("template_id", list(_QUESTION))
async def test_each_allowed_template_and_scope_kind_binds_pinned_parameters(
    kind: ScopeKind,
    template_id: str,
) -> None:
    client = AsyncMock()
    client.run_query.return_value = [
        {"title": "duplicate-safe"},
    ]
    set_graph_client(client)
    token = _token(kind)
    state = agent_state(
        spatial_scope=token,
        spatial_relation=RetrievalSpatialRelation.EITHER,
    )

    result = await invoke_runtime_tool(
        query_knowledge_graph,
        {"question": _QUESTION[template_id]},
        state=state,
    )

    assert "duplicate-safe" in result
    client.run_query.assert_awaited_once()
    cypher, params = client.run_query.await_args.args[:2]
    assert cypher == SCOPED_TEMPLATES[(template_id, kind)]["cypher"]
    assert params["scope_key"] == token.scope_key
    assert params["compatible_revisions"] == list(
        token.compatible_derivation_revisions
    )
    assert client.run_query.await_args.kwargs["read_only"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question",
    [
        'who is "NATO"',
        'connected to "NATO"',
        'network around "NATO"',
        "top entities",
        "unmatched lowercase words",
    ],
)
async def test_unsupported_and_free_cypher_paths_execute_zero_queries(
    question: str,
) -> None:
    client = AsyncMock()
    set_graph_client(client)
    state = agent_state(
        spatial_scope=_token(ScopeKind.COUNTRY),
        spatial_relation=RetrievalSpatialRelation.EITHER,
    )

    with patch(
        "agents.tools.graph_query._free_cypher_fallback",
        AsyncMock(side_effect=AssertionError("scoped free Cypher bypass")),
    ):
        result = await invoke_runtime_tool(
            query_knowledge_graph,
            {"question": question},
            state=state,
        )

    marker, research = parse_spatial_application_marker(
        result,
        actual_tool_name="query_knowledge_graph",
    )
    assert marker is not None and marker.status == "unsupported"
    assert research.startswith("SPATIAL_SCOPE_UNSUPPORTED")
    client.run_query.assert_not_awaited()


@pytest.mark.asyncio
async def test_scoped_graph_failure_does_not_fallback_or_retry() -> None:
    client = AsyncMock()
    client.run_query.side_effect = RuntimeError("neo4j down")
    set_graph_client(client)
    state = agent_state(
        spatial_scope=_token(ScopeKind.COUNTRY),
        spatial_relation=RetrievalSpatialRelation.EITHER,
    )

    with patch(
        "agents.tools.graph_query._free_cypher_fallback",
        AsyncMock(side_effect=AssertionError("scoped free Cypher bypass")),
    ):
        result = await invoke_runtime_tool(
            query_knowledge_graph,
            {"question": "timeline of Kyiv"},
            state=state,
        )

    assert "failed" in result.lower()
    client.run_query.assert_awaited_once()


@pytest.mark.asyncio
async def test_about_relation_is_unsupported_before_scoped_occurrence_query() -> None:
    client = AsyncMock()
    set_graph_client(client)
    state = agent_state(
        spatial_scope=_token(ScopeKind.COUNTRY),
        spatial_relation=RetrievalSpatialRelation.ABOUT,
    )

    result = await invoke_runtime_tool(
        query_knowledge_graph,
        {"question": 'events about "NATO"'},
        state=state,
    )

    marker, research = parse_spatial_application_marker(
        result,
        actual_tool_name="query_knowledge_graph",
    )
    assert marker is not None and marker.status == "unsupported"
    assert marker.detail_code == "spatial-relation-not-allowlisted"
    assert research.startswith("SPATIAL_SCOPE_UNSUPPORTED")
    client.run_query.assert_not_awaited()
