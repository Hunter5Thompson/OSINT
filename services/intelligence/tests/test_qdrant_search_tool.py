"""Tests for qdrant_search tool output budgeting."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agents.tools.qdrant_search import TOOL_OUTPUT_MAX_CHARS, qdrant_search


class TestQdrantSearchTool:
    @pytest.mark.asyncio
    async def test_dedupes_graph_context_and_caps_output(self):
        graph_context = "[Knowledge Graph Context]\n" + "\n".join(
            f"  Entity{i} (Location) --[MENTIONS]-> Event{i} (Event)"
            for i in range(200)
        )
        results = [
            {
                "score": 0.9 - i * 0.01,
                "title": f"Result {i}",
                "source": "test",
                "region": "N/A",
                "content": "source text " * 200,
                "graph_context": graph_context,
            }
            for i in range(5)
        ]

        with patch(
            "agents.tools.qdrant_search.enhanced_search",
            AsyncMock(return_value=results),
        ):
            output = await qdrant_search.ainvoke({"query": "bundeswehr strategy"})

        assert len(output) <= TOOL_OUTPUT_MAX_CHARS + 64
        assert output.count("[Knowledge Graph Context]") == 1
        assert "truncated" in output
