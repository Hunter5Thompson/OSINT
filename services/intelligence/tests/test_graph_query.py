"""Tests for graph_query tool — template routing + free Cypher fallback."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from agents.tools.graph_query import (
    route_to_template,
    execute_graph_query,
    _format_results,
)


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
    async def test_fallback_validates_readonly(self):
        mock_client = AsyncMock()
        mock_client.run_query.return_value = []

        result = await execute_graph_query(
            cypher="CREATE (n:Test) RETURN n",
            params={},
            graph_client=mock_client,
        )

        mock_client.run_query.assert_not_called()
        assert "rejected" in result.lower() or "blocked" in result.lower()

    @pytest.mark.asyncio
    async def test_fallback_injects_limit(self):
        mock_client = AsyncMock()
        mock_client.run_query.return_value = []

        await execute_graph_query(
            cypher="MATCH (n:Entity) RETURN n",
            params={},
            graph_client=mock_client,
        )

        call_args = mock_client.run_query.call_args
        executed_cypher = call_args.args[0] if call_args.args else call_args.kwargs.get("cypher", "")
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
    async def test_semicolon_in_free_cypher_rejected(self):
        mock_client = AsyncMock()

        result = await execute_graph_query(
            cypher="MATCH (n) RETURN n; DROP INDEX foo",
            params={},
            graph_client=mock_client,
        )

        mock_client.run_query.assert_not_called()
        assert "rejected" in result.lower() or "blocked" in result.lower()
