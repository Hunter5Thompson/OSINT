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

        assert len(output) <= TOOL_OUTPUT_MAX_CHARS
        assert output.count("[Graph Context]") == 1

    @pytest.mark.asyncio
    async def test_emits_parsable_evidence_blocks_with_provider(self):
        from rag.evidence import parse_evidence_refs
        results = [
            {
                "score": 0.9, "source_type": "rss", "provider": "reuters.com",
                "title": "Tanker seized", "content": "body " * 50,
                "url": "https://reuters.com/a", "content_hash": "h1",
            },
            {
                "score": 0.8, "source_type": "dataset", "provider": "usgs.gov",
                "title": "Quake", "content": "m6 " * 50, "content_hash": "h2",
            },
        ]
        from unittest.mock import AsyncMock, patch
        with patch(
            "agents.tools.qdrant_search.enhanced_search",
            AsyncMock(return_value=results),
        ):
            out = await qdrant_search.ainvoke({"query": "baltic tanker"})
        refs = parse_evidence_refs(out)
        assert {r.provider for r in refs} == {"reuters.com", "usgs.gov"}
        assert refs[0].provider == "reuters.com"  # higher score first

    @pytest.mark.asyncio
    async def test_output_never_exceeds_cap_with_full_pack_no_graph(self):
        """Full evidence pack + long query + no graph: output must stay within cap.

        Uses title_len=130 / provider_len=10 / content 700 chars to force the pack
        close to the budget limit, exposing the off-by-header bug without graph_text.
        """
        from unittest.mock import AsyncMock, patch
        from agents.tools.qdrant_search import TOOL_OUTPUT_MAX_CHARS
        results = [
            {"score": 0.9 - i * 0.01, "source_type": "rss", "provider": "p" * 10,
             "title": "T" * 130, "content": "x" * 700, "content_hash": f"h{i}"}
            for i in range(20)
        ]
        with patch("agents.tools.qdrant_search.enhanced_search", AsyncMock(return_value=results)):
            out = await qdrant_search.ainvoke({"query": "q" * 100})
        assert len(out) <= TOOL_OUTPUT_MAX_CHARS
