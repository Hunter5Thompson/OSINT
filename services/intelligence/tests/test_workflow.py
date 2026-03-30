"""Tests for the intelligence pipeline workflow graphs."""

from graph.state import AgentState
from graph.workflow import build_react_graph, build_legacy_graph


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
