"""Inner failures and empty research must not become ordinary reports."""

from unittest.mock import AsyncMock

import httpx
import pytest
from langchain_core.messages import AIMessage

import graph.workflow as workflow
import main


@pytest.mark.parametrize("stage", ["research", "synthesis"])
async def test_inner_failure_reaches_http(monkeypatch, stage):
    research, synthesis = AsyncMock(), AsyncMock()
    research.ainvoke.return_value = AIMessage(content="done")
    synthesis.ainvoke.return_value = AIMessage(content="normal report")
    (research if stage == "research" else synthesis).ainvoke.side_effect = RuntimeError(
        "private failure"
    )
    monkeypatch.setattr(workflow, "create_react_agent", lambda tools: research)
    monkeypatch.setattr(workflow, "create_synthesis_llm", lambda: synthesis)
    monkeypatch.setattr(workflow, "_ensure_graph_client", lambda: None)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://test"
    ) as c:
        r = await c.post(
            "/query",
            json={
                "query": "test",
                "spatial_relation": "either",
                "grounding_evidence": [
                    {
                        "source_type": "dataset",
                        "provider": "odin-country-almanac",
                        "doc_id": "fixture",
                        "title": "Fixture",
                        "content": "Real structural evidence.",
                    }
                ],
            },
        )
    assert r.status_code == 502
    assert r.json()["status"] == "failed"
    assert r.json()["code"] == "INTEL_PIPELINE_FAILED"
    assert "private failure" not in r.text
    if stage == "research":
        synthesis.ainvoke.assert_not_awaited()


async def test_empty_research_is_not_a_model_assessment(monkeypatch):
    llm = AsyncMock()
    monkeypatch.setattr(workflow, "create_synthesis_llm", lambda: llm)
    result = await workflow.react_synthesis_node({"query": "test", "messages": []})
    llm.ainvoke.assert_not_awaited()
    assert result["answerability"] == "insufficient_evidence"
    assert result["threat_assessment"] is None
    assert result["confidence"] is None
    assert result["assessment_status"]["threat"] == "not_assessed"


async def test_provider_failure_is_not_empty_evidence(monkeypatch):
    from langchain_core.tools import tool

    from tests.tool_runtime import agent_state

    @tool
    async def probe():
        """Fail at the provider boundary."""
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(workflow, "tools_for_state", lambda state: [probe])
    state = agent_state(
        messages=[
            AIMessage(content="", tool_calls=[{"name": "probe", "args": {}, "id": "probe-1"}])
        ]
    )
    from tests.test_tool_budget import _tool_graph

    state = await _tool_graph().ainvoke(state)
    result = await workflow.react_synthesis_node(state)
    assert result.get("error")
    assert result.get("answerability") != "insufficient_evidence"


@pytest.mark.parametrize("provider", ["rss", "gdelt", "vision"])
async def test_provider_exception_has_structured_failure(provider, monkeypatch):
    from unittest.mock import patch

    from langchain_core.tools import ToolException

    from agents.tools.gdelt_query import gdelt_query
    from agents.tools.rss_fetch import rss_fetch
    from agents.tools.vision import analyze_image
    from tests.tool_runtime import agent_state, invoke_runtime_tool

    if provider == "rss":
        target = "agents.tools.rss_fetch.httpx.AsyncClient"
        tool, args, state = rss_fetch, {"feed_url": "https://example.test/rss"}, agent_state()
    elif provider == "gdelt":
        from config import settings

        monkeypatch.setattr(settings, "enable_gdelt_doc_tool", True)
        target = "agents.tools.gdelt_query.httpx.AsyncClient"
        tool, args, state = gdelt_query, {"query": "test"}, agent_state()
    else:
        # The image loader must report failure, not evidence absence.
        target = "agents.tools.vision._load_image"
        tool, args, state = (
            analyze_image,
            {"question": "describe"},
            agent_state(image_url="https://example.test/image.png"),
        )
    with patch(target, side_effect=RuntimeError("private failure")), pytest.raises(ToolException):
        await invoke_runtime_tool(tool, args, state=state)
