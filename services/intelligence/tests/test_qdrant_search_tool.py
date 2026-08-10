"""Tests for qdrant_search tool output budgeting."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agents.tools.qdrant_search import TOOL_OUTPUT_MAX_CHARS, qdrant_search
from rag.corpus_policy import analysis_filter, realtime_filter
from spatial import (
    RetrievalSpatialRelation,
    ScopeKind,
    SpatialScopeTokenV1,
    combine_filters,
    compile_qdrant_scope_filter,
    parse_spatial_application_marker,
)
from tests.tool_runtime import agent_state, invoke_runtime_tool


def _prose(min_chars: int = 80) -> str:
    """Realistic analysis prose (multiple words + sentence punctuation) of at least
    `min_chars`. Analysis points need real content now that the read-path content-quality
    gate (corpus_policy.validate_lane) drops empty / single-token / no-sentence chunks."""
    s = "Western naval forces tracked the tanker through the strait and assessed the risk. "
    out = s
    while len(out) < min_chars:
        out += s
    return out


def _ukraine_token() -> SpatialScopeTokenV1:
    return SpatialScopeTokenV1(
        scope_key="country:UKR",
        kind=ScopeKind.COUNTRY,
        catalog_revision="spatial-v1-e76a16bff799",
        derivation_revision="spatial-derive-v1-d30efa07e141",
        boundary_policy="odin-reference-v1",
        compatible_derivation_revisions=(
            "spatial-derive-v1-d30efa07e141",
            "spatial-derive-v1-aaaaaaaaaaaa",
        ),
    )


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
                "content": _prose(2000),
                "graph_context": graph_context,
            }
            for i in range(5)
        ]

        with patch(
            "agents.tools.qdrant_search.enhanced_search",
            AsyncMock(side_effect=[results, []]),
        ):
            output = await invoke_runtime_tool(
                qdrant_search, {"query": "bundeswehr strategy"}
            )

        assert len(output) <= TOOL_OUTPUT_MAX_CHARS
        assert output.count("[Graph Context]") == 1

    @pytest.mark.asyncio
    async def test_emits_parsable_evidence_blocks_with_provider(self):
        from rag.evidence import parse_evidence_refs
        results = [
            {
                "score": 0.9, "source": "rss", "source_type": "rss",
                "provider": "reuters.com", "title": "Tanker seized",
                "content": _prose(300), "url": "https://reuters.com/a",
                "content_hash": "h1",
            },
            {
                "score": 0.8, "source": "rss", "feed_name": "RUSI Commentary",
                "title": "RUSI analysis", "content": _prose(300),
                "content_hash": "h2",
            },
        ]
        with patch(
            "agents.tools.qdrant_search.enhanced_search",
            AsyncMock(side_effect=[results, []]),
        ):
            out = await invoke_runtime_tool(qdrant_search, {"query": "baltic tanker"})
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
             "title": "T" * 130, "content": _prose(700), "content_hash": f"h{i}"}
            for i in range(20)
        ]
        with patch("agents.tools.qdrant_search.enhanced_search",
                   AsyncMock(side_effect=[results, []])):
            out = await invoke_runtime_tool(qdrant_search, {"query": "q" * 100})
        assert len(out) <= TOOL_OUTPUT_MAX_CHARS


class TestTwoLaneScoping:
    def _lane_mock(self, analysis, realtime):
        # enhanced_search is called analysis-lane first, realtime-lane second
        return AsyncMock(side_effect=[analysis, realtime])

    async def test_excludes_gkg_and_firms_keeps_analysis(self):
        from agents.tools import qdrant_search as qs

        analysis = [
            {"source": "rss", "feed_name": "CSIS", "title": "Tank view",
             "content": _prose(), "score": 0.8},
            {"source": "rss", "feed_name": "RUSI Commentary", "title": "RUSI",
             "content": _prose(), "score": 0.7},
        ]
        realtime = []  # nothing cleared the 0.45 bar
        with patch("agents.tools.qdrant_search.enhanced_search",
                   self._lane_mock(analysis, realtime)):
            out = await invoke_runtime_tool(qs, {"query": "taiwan strait"})

        assert "CSIS" in out or "Tank view" in out
        assert "gdelt_gkg" not in out
        assert "firms" not in out

    async def test_at_most_one_realtime_marked(self):
        from agents.tools import qdrant_search as qs

        analysis = [{"source": "rss", "feed_name": "CSIS", "title": f"A{i}",
                     "content": _prose(), "score": 0.8} for i in range(5)]
        realtime = [{"source": "telegram", "telegram_channel": "wartranslated",
                     "title": "RT lead", "content": "raw", "score": 0.6}]
        with patch("agents.tools.qdrant_search.enhanced_search",
                   self._lane_mock(analysis, realtime)):
            out = await invoke_runtime_tool(qs, {"query": "kharkiv"})

        assert out.count('"source_class":"realtime"') == 1

    async def test_guard_drops_leaked_unvetted_telegram(self):
        from agents.tools import qdrant_search as qs

        analysis = [{"source": "rss", "feed_name": "CSIS", "title": "A",
                     "content": _prose(), "score": 0.8}]
        # a rybar item leaks past the (mocked) filter — guard must drop it
        realtime = [{"source": "telegram", "telegram_channel": "rybar",
                     "title": "propaganda", "content": "raw", "score": 0.9}]
        with patch("agents.tools.qdrant_search.enhanced_search",
                   self._lane_mock(analysis, realtime)):
            out = await invoke_runtime_tool(qs, {"query": "donbas"})

        assert "propaganda" not in out
        assert '"source_class":"realtime"' not in out

    async def test_guard_drops_injected_gkg_and_firms(self):
        from agents.tools import qdrant_search as qs

        # gkg + firms leak INTO the analysis lane past the (mocked) filter — the
        # output guard is the second barrier and must drop them (AC-2).
        analysis = [
            {"source": "rss", "feed_name": "CSIS", "title": "Real analysis",
             "content": _prose(), "score": 0.8},
            {"source": "gdelt_gkg", "doc_id": "gdelt:gkg:9",
             "title": "gdelt:gkg:9", "score": 0.95},
            {"source": "firms", "title": "thermal anomaly", "score": 0.9},
        ]
        with patch("agents.tools.qdrant_search.enhanced_search",
                   self._lane_mock(analysis, [])):
            out = await invoke_runtime_tool(qs, {"query": "taiwan strait"})

        assert "gdelt:gkg:9" not in out
        assert "thermal anomaly" not in out
        assert "Real analysis" in out or "CSIS" in out

    async def test_realtime_error_degrades_gracefully(self):
        from agents.tools import qdrant_search as qs

        analysis = [{"source": "rss", "feed_name": "CSIS", "title": "A",
                     "content": _prose(), "score": 0.8}]
        with patch(
            "agents.tools.qdrant_search.enhanced_search",
            AsyncMock(side_effect=[analysis, RuntimeError("realtime down")]),
        ):
            out = await invoke_runtime_tool(qs, {"query": "kyiv"})

        assert "CSIS" in out or "A" in out          # analysis lane survives
        assert '"source_class":"realtime"' not in out
        marker, _ = parse_spatial_application_marker(
            out,
            actual_tool_name="qdrant_search",
        )
        assert marker is not None
        assert marker.status == "applied"
        assert marker.completeness == "partial"

    async def test_emitted_order_preserves_tier_rank_not_dense_score(self):
        from agents.tools import qdrant_search as qs

        # analysis arrives ALREADY in tier order (think-tank first) even though the
        # think-tank has a LOWER raw dense score than the local source. The emitted
        # pack must keep tier order, not re-sort by dense score.
        analysis = [
            {"source": "rss", "feed_name": "CSIS", "title": "TANKVIEW",
             "content": _prose(), "score": 0.40},
            {"source": "rss", "feed_name": "Local Paper", "title": "LOCALVIEW",
             "content": _prose(), "score": 0.95},
        ]
        with patch("agents.tools.qdrant_search.enhanced_search",
                   self._lane_mock(analysis, [])):
            out = await invoke_runtime_tool(qs, {"query": "x"})

        assert out.index("TANKVIEW") < out.index("LOCALVIEW")


class TestRuntimeSpatialScoping:
    async def test_adds_scope_filter_without_weakening_either_lane_policy(self):
        search = AsyncMock(side_effect=[[], []])
        token = _ukraine_token()
        state = agent_state(
            spatial_scope=token,
            spatial_relation=RetrievalSpatialRelation.EITHER,
        )

        with patch("agents.tools.qdrant_search.enhanced_search", search):
            await invoke_runtime_tool(qdrant_search, {"query": "ukraine"}, state=state)

        assert search.await_count == 2
        spatial_filter = compile_qdrant_scope_filter(
            token, RetrievalSpatialRelation.EITHER
        )
        assert search.await_args_list[0].kwargs["query_filter"] == combine_filters(
            analysis_filter(), spatial_filter
        )
        assert search.await_args_list[1].kwargs["query_filter"] == combine_filters(
            realtime_filter(), spatial_filter
        )
        assert all("region" not in call.kwargs for call in search.await_args_list)
        assert all(call.kwargs["raise_on_failure"] is True for call in search.await_args_list)

    async def test_analysis_outage_is_reported_failed(self):
        state = agent_state(
            spatial_scope=_ukraine_token(),
            spatial_relation=RetrievalSpatialRelation.EITHER,
        )
        with patch(
            "agents.tools.qdrant_search.enhanced_search",
            AsyncMock(side_effect=RuntimeError("qdrant down")),
        ):
            output = await invoke_runtime_tool(
                qdrant_search,
                {"query": "ukraine"},
                state=state,
            )

        marker, research = parse_spatial_application_marker(
            output,
            actual_tool_name="qdrant_search",
        )
        assert marker is not None
        assert marker.status == "failed"
        assert marker.completeness == "unknown"
        assert "qdrant down" in research

    @pytest.mark.parametrize(
        "side_effect",
        [
            [[], []],
            RuntimeError("qdrant down"),
            [[], RuntimeError("realtime partial")],
        ],
    )
    async def test_empty_partial_and_outage_never_retry_without_scope(
        self,
        side_effect,
    ):
        search = AsyncMock(side_effect=side_effect)
        token = _ukraine_token()
        state = agent_state(
            spatial_scope=token,
            spatial_relation=RetrievalSpatialRelation.OCCURRENCE,
        )

        with patch("agents.tools.qdrant_search.enhanced_search", search):
            output = await invoke_runtime_tool(
                qdrant_search,
                {"query": "ukraine"},
                state=state,
            )

        expected_spatial = compile_qdrant_scope_filter(
            token, RetrievalSpatialRelation.OCCURRENCE
        )
        expected_filters = {
            repr(combine_filters(analysis_filter(), expected_spatial)),
            repr(combine_filters(realtime_filter(), expected_spatial)),
        }
        assert search.await_count <= 2
        assert all(
            repr(call.kwargs["query_filter"]) in expected_filters
            for call in search.await_args_list
        )

        marker, _ = parse_spatial_application_marker(
            output,
            actual_tool_name="qdrant_search",
        )
        assert marker is not None
