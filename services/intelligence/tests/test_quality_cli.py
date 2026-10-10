"""Exercise the harness seam with real tool/synthesis nodes and fake providers."""
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage

import evaluation.quality_cli as cli
import graph.workflow as workflow
from evaluation.quality import evaluate_run


async def test_fixture_runner_records_structural_consumption_and_restores_factory(monkeypatch):
    corpus, digest = cli.load_corpus()
    original_tools = workflow.tools_for_state
    original_budget = workflow._budget_research_segments
    llm = AsyncMock()
    llm.ainvoke.return_value = AIMessage(
        content="Threat Assessment: MODERATE\nConfidence Level: low confidence"
    )
    monkeypatch.setattr(workflow, "create_synthesis_llm", lambda: llm)

    class GraphProbe:
        async def ainvoke(self, state):
            tools = workflow.tools_for_state(state)
            assert len(tools) == 1 and tools[0].name == "qdrant_search"
            message = await tools[0].ainvoke({
                "type": "tool_call", "name": "qdrant_search", "id": "synthetic",
                "args": {"query": state["query"]},
            })
            result = {**state, "messages": [message], "iteration": 2,
                      "tool_calls_count": 1, "tool_trace": [{"tool": "qdrant_search"}]}
            return {**result, **await workflow.react_synthesis_node(result)}

        def compile(self):
            return self

    monkeypatch.setattr(workflow, "build_react_graph", GraphProbe)
    run = await cli.run_fixture_graph(corpus, digest, None)
    assert len(run["records"]) == 36 and llm.ainvoke.await_count == 36
    assert workflow.tools_for_state is original_tools
    assert workflow._budget_research_segments is original_budget
    verdict = evaluate_run(corpus, digest, run)
    assert verdict["technical"]["status"] == "PASS"
    assert verdict["latency"]["status"] == "UNKNOWN"
    assert verdict["human"]["status"] == "PENDING"
    assert verdict["status"] == "INCOMPLETE"


async def test_dispatch_failure_retains_unknown_start_accounting(monkeypatch):
    corpus, digest = cli.load_corpus()
    corpus = {**corpus, "cases": corpus["cases"][:1], "repetitions": 1}

    class FailingGraph:
        async def ainvoke(self, state):
            raise RuntimeError("synthetic failure")

        def compile(self):
            return self

    monkeypatch.setattr(workflow, "build_react_graph", FailingGraph)
    run = await cli.run_fixture_graph(corpus, digest, None)
    row = run["records"][0]
    assert row["tool_starts"] is None and row["agent_turns"] is None
    assert row["error_code"] == "RuntimeError"
    assert evaluate_run(corpus, digest, run)["technical"]["status"] == "FAIL"


def test_corpus_tampering_is_rejected_before_preparation(tmp_path, monkeypatch):
    path = tmp_path / "analysis-quality-v1.json"
    path.write_bytes(cli.CORPUS_PATH.read_bytes() + b" ")
    path.with_suffix(".sha256").write_text(cli.CORPUS_PATH.with_suffix(".sha256").read_text())
    monkeypatch.setattr(cli, "CORPUS_PATH", path)
    with pytest.raises(ValueError, match="hash mismatch"):
        cli.load_corpus()
