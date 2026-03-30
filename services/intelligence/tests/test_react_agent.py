"""Tests for ReAct agent workflow — tool binding, guards, fallback."""

import pytest
from unittest.mock import MagicMock

from agents.react_agent import (
    REACT_SYSTEM_PROMPT,
    create_react_agent,
    should_continue,
    guard_check,
)
from graph.state import AgentState


def _make_state(**overrides) -> AgentState:
    """Helper to create a valid AgentState with defaults."""
    base: AgentState = {
        "query": "test",
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
    base.update(overrides)
    return base


class TestSystemPrompt:
    def test_mentions_all_tools(self):
        prompt = REACT_SYSTEM_PROMPT
        assert "qdrant_search" in prompt
        assert "query_knowledge_graph" in prompt
        assert "classify_event" in prompt
        assert "analyze_image" in prompt
        assert "gdelt_query" in prompt
        assert "rss_fetch" in prompt

    def test_includes_tool_budget(self):
        assert "8" in REACT_SYSTEM_PROMPT or "max" in REACT_SYSTEM_PROMPT.lower()


class TestGuardCheck:
    def test_under_limit_continues(self):
        state = _make_state(tool_calls_count=3, iteration=2)
        assert guard_check(state) == "continue"

    def test_tool_calls_exceeded_stops(self):
        state = _make_state(tool_calls_count=9, iteration=2)
        assert guard_check(state) == "stop"

    def test_iterations_exceeded_stops(self):
        state = _make_state(tool_calls_count=2, iteration=6)
        assert guard_check(state) == "stop"


class TestShouldContinue:
    def test_no_tool_calls_goes_to_synthesis(self):
        mock_msg = MagicMock()
        mock_msg.tool_calls = []
        state = _make_state(messages=[mock_msg], tool_calls_count=1, iteration=1)
        assert should_continue(state) == "synthesis"

    def test_has_tool_calls_continues(self):
        mock_msg = MagicMock()
        mock_msg.tool_calls = [{"name": "qdrant_search", "args": {}}]
        state = _make_state(messages=[mock_msg], tool_calls_count=1, iteration=1)
        assert should_continue(state) == "tools"

    def test_empty_messages_goes_to_synthesis(self):
        state = _make_state(messages=[])
        assert should_continue(state) == "synthesis"

    def test_guard_exceeded_goes_to_synthesis(self):
        mock_msg = MagicMock()
        mock_msg.tool_calls = [{"name": "qdrant_search", "args": {}}]
        state = _make_state(messages=[mock_msg], tool_calls_count=10, iteration=1)
        assert should_continue(state) == "synthesis"
