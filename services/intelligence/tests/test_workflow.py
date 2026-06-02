"""Tests for the intelligence pipeline workflow graphs."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import ToolMessage

from graph.state import AgentState
from graph.workflow import (
    REACT_TOOL_HISTORY_MAX_CHARS,
    SYNTHESIS_RESEARCH_MAX_CHARS,
    _clip_text,
    _compact_tool_messages,
    build_legacy_graph,
    build_react_graph,
    run_intelligence_query,
)


class TestWorkflowGraph:
    def test_react_graph_compiles(self) -> None:
        """The ReAct workflow graph should compile without errors."""
        graph = build_react_graph()
        compiled = graph.compile()
        assert compiled is not None

    def test_legacy_graph_compiles(self) -> None:
        """The legacy workflow graph should compile without errors."""
        graph = build_legacy_graph()
        compiled = graph.compile()
        assert compiled is not None

    def test_initial_state_valid(self) -> None:
        """Initial state should have all required fields."""
        state: AgentState = {
            "query": "Test query",
            "image_url": None,
            "messages": [],
            "tool_calls_count": 0,
            "iteration": 0,
            "osint_results": [],
            "analysis": "",
            "synthesis": "",
            "executive_summary": "",
            "key_findings": [],
            "threat_assessment": "",
            "confidence": 0.0,
            "sources_used": [],
            "agent_chain": [],
            "tool_trace": [],
            "error": None,
        }
        assert state["query"] == "Test query"
        assert state["iteration"] == 0
        assert state["error"] is None
        assert state["image_url"] is None
        assert state["tool_calls_count"] == 0

    def test_clip_text_marks_omitted_content(self) -> None:
        text = "x" * (SYNTHESIS_RESEARCH_MAX_CHARS + 100)

        clipped = _clip_text(text, SYNTHESIS_RESEARCH_MAX_CHARS)

        assert len(clipped) < len(text)
        assert "truncated 100 chars" in clipped

    def test_compact_tool_messages_preserves_recent_outputs(self) -> None:
        old_tool = ToolMessage(content="old " * 2000, tool_call_id="old")
        new_tool = ToolMessage(content="new " * 2000, tool_call_id="new")

        compacted = _compact_tool_messages([old_tool, new_tool])

        assert len("".join(str(m.content) for m in compacted)) <= (
            REACT_TOOL_HISTORY_MAX_CHARS + 512
        )
        assert compacted[0].tool_call_id == "old"
        assert compacted[1].tool_call_id == "new"
        assert "new " in compacted[1].content


@pytest.mark.asyncio
async def test_react_failure_propagates_instead_of_silent_legacy_fallback() -> None:
    """A ReAct failure (use_legacy=False) must propagate out of
    run_intelligence_query so the backend sees a non-2xx — never a silent legacy
    (no-sources) fallback or a mode:'error' HTTP-200 dict (Phase 4 / C7)."""
    react = MagicMock(ainvoke=AsyncMock(side_effect=RuntimeError("react exploded")))
    legacy = MagicMock(
        ainvoke=AsyncMock(return_value={"sources_used": [], "synthesis": "legacy"}),
    )
    with (
        patch("graph.workflow.react_graph", react),
        patch("graph.workflow.legacy_graph", legacy),
        patch("graph.workflow._ensure_graph_client"),
        pytest.raises(RuntimeError, match="react exploded"),
    ):
        await run_intelligence_query("test query", use_legacy=False)

    # The ReAct path must not silently fall back to the legacy pipeline.
    legacy.ainvoke.assert_not_awaited()
