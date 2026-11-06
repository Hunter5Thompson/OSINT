"""Actual ToolNode, Qdrant tool, synthesis and HTTP route; providers are frozen fakes."""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from langchain_core.messages import AIMessage

import graph.workflow as workflow
import main
from agents.tools.qdrant_search import qdrant_search
from graph.assessment import parse_assessment
from tests.test_reviewed_evidence_contract import PAYLOADS


@pytest.mark.parametrize("payload", PAYLOADS, ids=lambda p: p["review"]["candidate_id"])
async def test_claim_survives_real_query_route(monkeypatch, payload):
    import importlib

    qdrant_module = importlib.import_module("agents.tools.qdrant_search")
    from rag.evidence import to_evidence_item

    search = AsyncMock(side_effect=[[{**payload, "score": 1.0}], []])
    monkeypatch.setattr(qdrant_module, "enhanced_search", search)
    monkeypatch.setattr(workflow, "tools_for_state", lambda state: [qdrant_search])
    monkeypatch.setattr(workflow, "_ensure_graph_client", lambda: None)
    research = AsyncMock()
    research.ainvoke.side_effect = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "lookup",
                    "name": "qdrant_search",
                    "args": {"query": payload["review"]["candidate_id"]},
                }
            ],
        ),
        AIMessage(content="Research complete"),
    ]
    monkeypatch.setattr(workflow, "create_react_agent", lambda tools: research)
    synthesis = AsyncMock()
    item = to_evidence_item(payload)
    synthesis.ainvoke.return_value = AIMessage(
        content=f"Belegt [{item.evidence_id}].\n"
        "Threat Assessment: MODERATE\nConfidence Level: low confidence"
    )
    monkeypatch.setattr(workflow, "create_synthesis_llm", lambda: synthesis)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/query",
            json={
                "query": "Read the reviewed claim",
                "spatial_relation": "either",
                "research_mode": "historical",
            },
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["evidence_summary"][0]["review"] == item.review.model_dump(mode="json")
    assert body["evidence_summary"][0]["evidence_id"] == item.evidence_id
    assert [e["status"] for e in body["tool_events"]] == ["requested", "started", "succeeded"]
    assert len(body["tool_trace"]) == 1
    for messages in [
        research.ainvoke.call_args_list[1].args[0],
        synthesis.ainvoke.call_args.args[0],
    ]:
        prompt = "\n".join(str(m.content) for m in messages)
        header = next(line for line in prompt.splitlines() if line.startswith("[EVIDENCE] "))
        assert json.loads(header.removeprefix("[EVIDENCE] "))["review"] == item.review.model_dump(
            mode="json"
        )


REPLAYS = json.loads(
    (Path(__file__).parents[3] / "tests/fixtures/assessment-replay-12.json").read_text()
)


@pytest.mark.parametrize("row", REPLAYS, ids=lambda r: r["case"])
def test_historical_reports_keep_correct_assessments(row):
    parsed = parse_assessment(row["analysis"])
    assert parsed.threat == row["expected"]["threat"]
    assert parsed.confidence == row["expected"]["confidence"]
    assert list(parsed.issues) == row["expected"]["issues"]
