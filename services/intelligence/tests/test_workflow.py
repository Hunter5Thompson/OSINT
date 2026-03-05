"""Tests for the intelligence pipeline workflow graph."""

from graph.state import AgentState
from graph.workflow import build_graph


class TestWorkflowGraph:
    def test_graph_compiles(self) -> None:
        """The workflow graph should compile without errors."""
        graph = build_graph()
        compiled = graph.compile()
        assert compiled is not None

    def test_initial_state_valid(self) -> None:
        """Initial state should have all required fields."""
        state: AgentState = {
            "query": "Test query",
            "messages": [],
            "osint_results": [],
            "analysis": "",
            "synthesis": "",
            "sources_used": [],
            "confidence": 0.0,
            "threat_assessment": "",
            "agent_chain": [],
            "iteration": 0,
            "error": None,
        }
        assert state["query"] == "Test query"
        assert state["iteration"] == 0
        assert state["error"] is None
