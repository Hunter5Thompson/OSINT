"""Tests for graph_query tool — template routing + free Cypher fallback."""

from unittest.mock import AsyncMock, patch

import pytest

from agents.tools.graph_query import (
    _format_results,
    execute_graph_query,
    query_knowledge_graph,
    route_to_template,
    set_graph_client,
)
from config import settings
from graph.read_queries import validate_cypher_readonly
from spatial import parse_spatial_application_marker
from tests.tool_runtime import agent_state, invoke_runtime_tool

_F15_COMMENT_QUOTE_ATTACKS = [
    pytest.param(
        "/* ' */ MATCH (n) DETACH DELETE n /* ' */",
        id="delete-hidden-by-block-comment-quotes",
    ),
    pytest.param(
        "/* ' */ LOAD CSV FROM 'http://127.0.0.1/x.csv' AS row "
        "RETURN row /* ' */",
        id="load-csv-hidden-by-block-comment-quotes",
    ),
    pytest.param(
        "/* ' */ CALL apoc.load.json('http://127.0.0.1/x.json') "
        "YIELD value RETURN value /* ' */",
        id="call-hidden-by-block-comment-quotes",
    ),
    pytest.param(
        "MATCH (n) // '\nMERGE (m:Entity {id: n.id}) // '\nRETURN n",
        id="merge-hidden-by-line-comment-quotes",
    ),
]


class TestRouteToTemplate:
    def test_returns_template_for_known_patterns(self):
        result = route_to_template("entity_lookup", {"name": "NATO"})
        assert result is not None
        assert result["mode"] == "template"
        assert result["template_id"] == "entity_lookup"

    def test_returns_none_for_unknown_pattern(self):
        result = route_to_template("unknown_intent", {})
        assert result is None


class TestFormatResults:
    def test_formats_list_of_dicts(self):
        rows = [
            {"name": "NATO", "type": "organization"},
            {"name": "EU", "type": "organization"},
        ]
        text = _format_results(rows)
        assert "NATO" in text
        assert "EU" in text

    def test_empty_results(self):
        text = _format_results([])
        assert "no results" in text.lower()

    def test_truncates_long_results(self):
        rows = [{"data": "x" * 500} for _ in range(20)]
        text = _format_results(rows, max_rows=5)
        assert text.count("data") <= 6  # header + 5 rows


class TestExecuteGraphQuery:
    @pytest.mark.asyncio
    async def test_template_mode_calls_graph_client(self):
        mock_client = AsyncMock()
        mock_client.run_query.return_value = [{"name": "PLA", "type": "organization"}]

        result = await execute_graph_query(
            template_id="entity_lookup",
            params={"name": "PLA"},
            graph_client=mock_client,
        )

        mock_client.run_query.assert_called_once()
        call_kwargs = mock_client.run_query.call_args
        assert call_kwargs.kwargs.get("read_only") is True
        assert "PLA" in result

    @pytest.mark.asyncio
    async def test_fallback_validates_readonly(self, monkeypatch):
        mock_client = AsyncMock()
        mock_client.run_query.return_value = []
        monkeypatch.setattr(settings, "enable_free_cypher", True, raising=False)

        result = await execute_graph_query(
            cypher="CREATE (n:Test) RETURN n",
            params={},
            graph_client=mock_client,
        )

        mock_client.run_query.assert_not_called()
        assert "rejected" in result.lower() or "blocked" in result.lower()

    @pytest.mark.asyncio
    async def test_fallback_injects_limit(self, monkeypatch):
        mock_client = AsyncMock()
        mock_client.run_query.return_value = []
        monkeypatch.setattr(settings, "enable_free_cypher", True, raising=False)

        await execute_graph_query(
            cypher="MATCH (n:Entity) RETURN n",
            params={},
            graph_client=mock_client,
        )

        call_args = mock_client.run_query.call_args
        executed_cypher = (
            call_args.args[0] if call_args.args else call_args.kwargs.get("cypher", "")
        )
        assert "LIMIT" in executed_cypher

    @pytest.mark.asyncio
    async def test_no_graph_client_returns_error(self):
        result = await execute_graph_query(
            template_id="entity_lookup",
            params={"name": "test"},
            graph_client=None,
        )
        assert "not available" in result.lower() or "no graph" in result.lower()

    @pytest.mark.asyncio
    async def test_query_timeout_handled(self):
        mock_client = AsyncMock()
        mock_client.run_query.side_effect = TimeoutError("query timed out")

        result = await execute_graph_query(
            template_id="entity_lookup",
            params={"name": "test"},
            graph_client=mock_client,
        )
        assert "failed" in result.lower() or "error" in result.lower()

    @pytest.mark.asyncio
    async def test_semicolon_in_free_cypher_rejected(self, monkeypatch):
        mock_client = AsyncMock()
        monkeypatch.setattr(settings, "enable_free_cypher", True, raising=False)

        result = await execute_graph_query(
            cypher="MATCH (n) RETURN n; DROP INDEX foo",
            params={},
            graph_client=mock_client,
        )

        mock_client.run_query.assert_not_called()
        assert "rejected" in result.lower() or "blocked" in result.lower()

    @pytest.mark.asyncio
    async def test_free_cypher_is_rejected_by_default_before_database_access(self, monkeypatch):
        mock_client = AsyncMock()
        monkeypatch.setattr(settings, "enable_free_cypher", False, raising=False)

        result = await execute_graph_query(
            cypher="MATCH (n:Entity) RETURN n",
            graph_client=mock_client,
        )

        assert "rejected" in result.lower()
        mock_client.run_query.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("cypher", _F15_COMMENT_QUOTE_ATTACKS)
    async def test_f15_comment_quote_attacks_never_reach_database(
        self, monkeypatch, cypher
    ):
        mock_client = AsyncMock()
        monkeypatch.setattr(settings, "enable_free_cypher", False, raising=False)

        # These are known false negatives of the legacy string-stripping check.
        assert validate_cypher_readonly(cypher) is True

        result = await execute_graph_query(cypher=cypher, graph_client=mock_client)

        assert "rejected" in result.lower()
        mock_client.run_query.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_template_limit_is_rejected_before_database_access(self):
        mock_client = AsyncMock()

        result = await execute_graph_query(
            template_id="events_by_entity",
            params={"name": "NATO", "limit": True},
            graph_client=mock_client,
        )

        assert "rejected" in result.lower()
        mock_client.run_query.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_template_id_is_rejected_without_database_access(self):
        mock_client = AsyncMock()

        result = await execute_graph_query(
            template_id="does_not_exist",
            graph_client=mock_client,
        )

        assert "rejected" in result.lower()
        assert "unknown" in result.lower()
        mock_client.run_query.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_intent_does_not_generate_free_cypher_when_disabled(
        self, monkeypatch
    ):
        mock_client = AsyncMock()
        set_graph_client(mock_client)
        monkeypatch.setattr(settings, "enable_free_cypher", False, raising=False)

        with patch(
            "agents.tools.graph_query._free_cypher_fallback",
            AsyncMock(side_effect=AssertionError("must not generate Cypher")),
        ) as fallback:
            result = await invoke_runtime_tool(
                query_knowledge_graph,
                {"question": "describe a topic with no matching template"},
                state=agent_state(),
            )

        marker, research = parse_spatial_application_marker(
            result, actual_tool_name="query_knowledge_graph"
        )
        assert marker is not None and marker.status == "unsupported"
        assert research.startswith("Query rejected")
        fallback.assert_not_awaited()
        mock_client.run_query.assert_not_awaited()
