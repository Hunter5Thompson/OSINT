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
                "source": "rss",
                "region": "N/A",
                "content": "source text " * 200,
                "graph_context": graph_context,
            }
            for i in range(5)
        ]

        with patch(
            "agents.tools.qdrant_search.enhanced_search",
            AsyncMock(side_effect=[results, []]),
        ):
            output = await qdrant_search.ainvoke({"query": "bundeswehr strategy"})

        assert len(output) <= TOOL_OUTPUT_MAX_CHARS
        assert output.count("[Graph Context]") == 1

    @pytest.mark.asyncio
    async def test_emits_parsable_evidence_blocks_with_provider(self):
        from rag.evidence import parse_evidence_refs
        results = [
            {
                "score": 0.9, "source": "rss", "source_type": "rss",
                "provider": "reuters.com", "title": "Tanker seized",
                "content": "body " * 50, "url": "https://reuters.com/a",
                "content_hash": "h1",
            },
            {
                "score": 0.8, "source": "rss", "feed_name": "RUSI Commentary",
                "title": "RUSI analysis", "summary": "rusi " * 50,
                "content_hash": "h2",
            },
        ]
        with patch(
            "agents.tools.qdrant_search.enhanced_search",
            AsyncMock(side_effect=[results, []]),
        ):
            out = await qdrant_search.ainvoke({"query": "baltic tanker"})
        refs = parse_evidence_refs(out)
        assert {r.provider for r in refs} == {"reuters.com", "rusi commentary"}
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
            {"score": 0.9 - i * 0.01, "source": "rss", "source_type": "rss",
             "provider": "p" * 10,
             "title": "T" * 130, "content": "x" * 700, "content_hash": f"h{i}"}
            for i in range(20)
        ]
        with patch("agents.tools.qdrant_search.enhanced_search",
                   AsyncMock(side_effect=[results, []])):
            out = await qdrant_search.ainvoke({"query": "q" * 100})
        assert len(out) <= TOOL_OUTPUT_MAX_CHARS


class TestTwoLaneScoping:
    def _lane_mock(self, analysis, realtime):
        # enhanced_search is called analysis-lane first, realtime-lane second
        return AsyncMock(side_effect=[analysis, realtime])

    async def test_excludes_gkg_and_firms_keeps_analysis(self):
        from agents.tools import qdrant_search as qs

        analysis = [
            {"source": "rss", "feed_name": "CSIS", "title": "Tank view",
             "summary": "deep analysis", "score": 0.8},
            {"source": "rss", "feed_name": "RUSI Commentary", "title": "RUSI",
             "summary": "more analysis", "score": 0.7},
        ]
        realtime = []  # nothing cleared the 0.45 bar
        with patch("agents.tools.qdrant_search.enhanced_search",
                   self._lane_mock(analysis, realtime)):
            out = await qs.ainvoke({"query": "taiwan strait"})

        assert "CSIS" in out or "Tank view" in out
        assert "gdelt_gkg" not in out
        assert "firms" not in out

    async def test_at_most_one_realtime_marked(self):
        from agents.tools import qdrant_search as qs

        analysis = [{"source": "rss", "feed_name": "CSIS", "title": f"A{i}",
                     "summary": "x", "score": 0.8} for i in range(5)]
        realtime = [{"source": "telegram", "telegram_channel": "wartranslated",
                     "title": "RT lead", "content": "raw", "score": 0.6}]
        with patch("agents.tools.qdrant_search.enhanced_search",
                   self._lane_mock(analysis, realtime)):
            out = await qs.ainvoke({"query": "kharkiv"})

        assert out.count('"source_class":"realtime"') == 1

    async def test_guard_drops_leaked_unvetted_telegram(self):
        from agents.tools import qdrant_search as qs

        analysis = [{"source": "rss", "feed_name": "CSIS", "title": "A",
                     "summary": "x", "score": 0.8}]
        # a rybar item leaks past the (mocked) filter — guard must drop it
        realtime = [{"source": "telegram", "telegram_channel": "rybar",
                     "title": "propaganda", "content": "raw", "score": 0.9}]
        with patch("agents.tools.qdrant_search.enhanced_search",
                   self._lane_mock(analysis, realtime)):
            out = await qs.ainvoke({"query": "donbas"})

        assert "propaganda" not in out
        assert '"source_class":"realtime"' not in out

    async def test_guard_drops_injected_gkg_and_firms(self):
        from agents.tools import qdrant_search as qs

        # gkg + firms leak INTO the analysis lane past the (mocked) filter — the
        # output guard is the second barrier and must drop them (AC-2).
        analysis = [
            {"source": "rss", "feed_name": "CSIS", "title": "Real analysis",
             "summary": "x", "score": 0.8},
            {"source": "gdelt_gkg", "doc_id": "gdelt:gkg:9",
             "title": "gdelt:gkg:9", "score": 0.95},
            {"source": "firms", "title": "thermal anomaly", "score": 0.9},
        ]
        with patch("agents.tools.qdrant_search.enhanced_search",
                   self._lane_mock(analysis, [])):
            out = await qs.ainvoke({"query": "taiwan strait"})

        assert "gdelt:gkg:9" not in out
        assert "thermal anomaly" not in out
        assert "Real analysis" in out or "CSIS" in out

    async def test_realtime_error_degrades_gracefully(self):
        from agents.tools import qdrant_search as qs

        analysis = [{"source": "rss", "feed_name": "CSIS", "title": "A",
                     "summary": "x", "score": 0.8}]
        with patch(
            "agents.tools.qdrant_search.enhanced_search",
            AsyncMock(side_effect=[analysis, RuntimeError("realtime down")]),
        ):
            out = await qs.ainvoke({"query": "kyiv"})

        assert "CSIS" in out or "A" in out          # analysis lane survives
        assert '"source_class":"realtime"' not in out
