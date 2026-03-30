"""Tests for Neo4j graph context injection via GraphClient."""

from unittest.mock import AsyncMock, patch
import pytest

from rag.graph_context import get_graph_context


class TestGraphContext:
    async def test_returns_context_for_entities(self):
        """Given entity names, return their Neo4j 2-hop neighborhood as text."""
        mock_graph = AsyncMock()
        mock_graph.run_query.return_value = [
            {"e_name": "NATO", "e_type": "organization", "rel": "INVOLVES",
             "connected_name": "Ukraine Conflict", "connected_type": "Event"},
            {"e_name": "NATO", "e_type": "organization", "rel": "ASSOCIATED_WITH",
             "connected_name": "EU", "connected_type": "Entity"},
        ]

        context = await get_graph_context(["NATO"], graph_client=mock_graph)

        assert "NATO" in context
        assert "Ukraine Conflict" in context or "EU" in context
        mock_graph.run_query.assert_called_once()
        # Verify read_only=True is used
        call_kwargs = mock_graph.run_query.call_args
        assert call_kwargs.kwargs.get("read_only") is True or \
               (len(call_kwargs.args) > 2 and call_kwargs.args[2] is True)

    async def test_two_hop_query(self):
        """Query should use *..2 for 2-hop neighborhood."""
        mock_graph = AsyncMock()
        mock_graph.run_query.return_value = []

        await get_graph_context(["NATO"], graph_client=mock_graph)

        cypher = mock_graph.run_query.call_args.args[0]
        assert "*..2" in cypher, f"Expected 2-hop query, got: {cypher}"

    async def test_empty_entities_returns_empty(self):
        mock_graph = AsyncMock()
        context = await get_graph_context([], graph_client=mock_graph)
        assert context == ""
        mock_graph.run_query.assert_not_called()

    async def test_no_graph_client_returns_empty(self):
        context = await get_graph_context(["NATO"], graph_client=None)
        assert context == ""

    async def test_graph_failure_returns_empty(self):
        """If Neo4j query fails, return empty string (graceful degradation)."""
        mock_graph = AsyncMock()
        mock_graph.run_query.side_effect = Exception("Neo4j down")

        context = await get_graph_context(["NATO"], graph_client=mock_graph)
        assert context == ""

    async def test_multiple_entities_queried(self):
        """Each entity gets its own query, results are merged."""
        mock_graph = AsyncMock()
        mock_graph.run_query.side_effect = [
            [{"e_name": "NATO", "e_type": "organization", "rel": "INVOLVES",
              "connected_name": "Event1", "connected_type": "Event"}],
            [{"e_name": "Russia", "e_type": "organization", "rel": "INVOLVES",
              "connected_name": "Event2", "connected_type": "Event"}],
        ]

        context = await get_graph_context(["NATO", "Russia"], graph_client=mock_graph)

        assert mock_graph.run_query.call_count == 2
        assert "NATO" in context
        assert "Russia" in context
