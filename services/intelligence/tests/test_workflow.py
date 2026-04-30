"""Tests for the intelligence pipeline workflow graphs."""

from langchain_core.messages import ToolMessage

from graph.state import AgentState
from graph.workflow import (
    REACT_TOOL_HISTORY_MAX_CHARS,
    SYNTHESIS_RESEARCH_MAX_CHARS,
    _clip_text,
    _compact_tool_messages,
    build_legacy_graph,
    build_react_graph,
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
