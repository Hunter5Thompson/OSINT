"""Current default crosses real HTTP route, graph, research and evidence codecs."""

import hashlib
from unittest.mock import AsyncMock

import httpx
import pytest
from langchain_core.messages import AIMessage
from pydantic import SecretStr

import graph.workflow as workflow
import main
from config import settings
from tests.test_current_research import ARTICLE, BODY


@pytest.fixture(autouse=True)
def owned_corpus_adapter(monkeypatch):
    monkeypatch.setattr("rag.public_query.prepare_public_query", AsyncMock(side_effect=lambda q: q))
    monkeypatch.setattr("rag.local_current.search_current_corpus", AsyncMock(return_value=[]))


async def test_zero_tool_calls_still_research_and_consume_current_original(monkeypatch):
    from datetime import UTC, datetime, timedelta

    real_client = httpx.AsyncClient
    requests = []

    def provider(request):
        requests.append(request)
        if request.url.path == "/search":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "url": ARTICLE,
                            "title": "Talks",
                            "content": "teaser",
                            "published_date": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"results": [{"url": ARTICLE, "raw_content": BODY}]})

    monkeypatch.setattr(
        "rag.current.httpx.AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(provider)),
    )
    monkeypatch.setattr(settings, "tavily_api_key", SecretStr("fixture"), raising=False)
    monkeypatch.setattr(settings, "tavily_api_url", "https://tavily.test", raising=False)
    monkeypatch.setattr(workflow, "_ensure_graph_client", lambda: None)
    monkeypatch.setattr(workflow, "notebook_context", AsyncMock(return_value=[]))
    model = AsyncMock()
    model.ainvoke.return_value = AIMessage(content="No tool calls")
    monkeypatch.setattr(workflow, "create_react_agent", lambda tools: model)
    identity = hashlib.sha256((ARTICLE + "\0" + BODY).encode()).hexdigest()[:24]
    synthesis = AsyncMock()
    synthesis.ainvoke.return_value = AIMessage(
        content=(
            f"Talks continued [ev-{identity}].\nThreat Assessment: NOT_ASSESSED\n"
            "Confidence Level: not assessed"
        )
    )
    monkeypatch.setattr(workflow, "create_synthesis_llm", lambda **kw: synthesis)
    async with real_client(
        transport=httpx.ASGITransport(app=main.app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/query", json={"query": "Iran negotiations", "spatial_relation": "either"}
        )
    assert response.status_code == 200, response.text
    result = response.json()
    assert [r.url.path for r in requests] == ["/search", "/extract"]
    assert result["research_coverage"]["situation"] == "evidence_available"
    assert result["evidence_summary"][0]["retrieval"]["content_kind"] == "fulltext"
    assert result["evidence_summary"][0]["excerpt"] == BODY
    assert result["verification_status"] == "unverified"
    assert "current_research" in result["agent_chain"]
    prompt = "\n".join(m.content for m in synthesis.ainvoke.call_args.args[0])
    assert BODY in prompt
    assert "scenario" in prompt.lower()


async def test_missing_provider_is_visible_and_historical_mode_can_opt_out(monkeypatch):
    monkeypatch.setattr(settings, "tavily_api_key", SecretStr(""), raising=False)
    monkeypatch.setattr(workflow, "_ensure_graph_client", lambda: None)
    monkeypatch.setattr(workflow, "notebook_context", AsyncMock(return_value=[]))
    model = AsyncMock()
    model.ainvoke.return_value = AIMessage(content="No tools")
    monkeypatch.setattr(workflow, "create_react_agent", lambda tools: model)
    current = await workflow.run_intelligence_query("Iran")
    assert current["status"] == "partial"
    assert current["research_coverage"]["situation"] == "research_failed"
    historical = await workflow.run_intelligence_query("Iran in 1979", research_mode="historical")
    assert historical["research_coverage"] is None
    assert "current_research" not in historical["agent_chain"]


async def test_followup_uses_same_time_window_cache_and_public_question(monkeypatch):
    import json
    from datetime import UTC, datetime, timedelta

    real_client = httpx.AsyncClient
    requests = []

    def provider(request):
        requests.append(request)
        if request.url.path == "/search":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "url": ARTICLE,
                            "title": "Iran",
                            "content": "teaser",
                            "published_date": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"results": [{"url": ARTICLE, "raw_content": BODY}]})

    monkeypatch.setattr(
        "rag.current.httpx.AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(provider)),
    )
    monkeypatch.setattr(settings, "tavily_api_key", SecretStr("fixture"))
    monkeypatch.setattr(settings, "tavily_api_url", "https://tavily.test")
    monkeypatch.setattr(workflow, "_ensure_graph_client", lambda: None)
    monkeypatch.setattr(workflow, "notebook_context", AsyncMock(return_value=[]))
    model = AsyncMock()
    model.ainvoke.side_effect = [
        AIMessage(
            content="",
            tool_calls=[
                {"name": "current_search", "args": {"focus": "counterevidence"}, "id": "followup"}
            ],
        ),
        AIMessage(content="Finished"),
    ]
    monkeypatch.setattr(workflow, "create_react_agent", lambda tools: model)
    identity = hashlib.sha256((ARTICLE + "\0" + BODY).encode()).hexdigest()[:24]
    synthesis = AsyncMock()
    synthesis.ainvoke.return_value = AIMessage(
        content=(
            f"Talks [ev-{identity}].\n"
            "Threat Assessment: NOT_ASSESSED\nConfidence Level: not assessed"
        )
    )
    monkeypatch.setattr(workflow, "create_synthesis_llm", lambda **kw: synthesis)
    result = await workflow.run_intelligence_query("Iran negotiations")
    assert [r.url.path for r in requests] == ["/search", "/extract", "/search"]
    searches = [json.loads(r.content) for r in requests if r.url.path == "/search"]
    assert searches[0]["start_date"] == searches[1]["start_date"]
    assert searches[1]["query"].startswith("Iran negotiations")
    assert len(result["research_coverage"]["attempts"]) == 4
    assert len(result["evidence_summary"]) == 1
