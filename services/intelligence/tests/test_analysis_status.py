"""G06 separates decoded fields, compatibility defaults and factual verification."""
from unittest.mock import AsyncMock

import httpx
import pytest
from langchain_core.messages import AIMessage

import graph.nodes as nodes
import graph.workflow as workflow


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize(
    ("report", "threat_status", "confidence_status", "issues"),
    [
        ("Threat Assessment: HIGH\nConfidence Level: low confidence", "declared", "declared", []),
        ("Threat Assessment: HIGHWAY\nConfidence Level: low confidence", "default", "declared",
         ["threat-invalid"]),
        ("Threat Assessment: HIGH\nNo confidence field", "declared", "default",
         ["confidence-missing"]),
        ("No fields", "default", "default", ["threat-missing", "confidence-missing"]),
    ],
)
async def test_final_node_exposes_each_field_origin(
    monkeypatch, legacy, report, threat_status, confidence_status, issues
):
    fake = AsyncMock()
    fake.ainvoke.return_value = AIMessage(content=report)
    module = nodes if legacy else workflow
    monkeypatch.setattr(module, "create_synthesis_llm", lambda: fake)
    node = nodes.synthesis_node if legacy else workflow.react_synthesis_node
    result = await node({"query": "synthetic", "messages": [], "analysis": "synthetic"})
    assert result.get("assessment_status") == {
        "threat": threat_status, "confidence": confidence_status, "issues": issues,
    }


async def test_real_query_serializes_status_without_promoting_it_to_facts(monkeypatch):
    import main

    fake = AsyncMock()
    fake.ainvoke.return_value = AIMessage(
        content="Threat Assessment: HIGHWAY\nConfidence Level: low confidence"
    )
    monkeypatch.setattr(workflow, "create_synthesis_llm", lambda: fake)
    monkeypatch.setattr(workflow, "_ensure_graph_client", lambda: None)

    class SynthesisGraph:
        async def ainvoke(self, state):
            return await workflow.react_synthesis_node(state)

    monkeypatch.setattr(workflow, "react_graph", SynthesisGraph())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/query", json={"query": "synthetic", "spatial_relation": "either"}
        )
    assert response.status_code == 200
    body = response.json()
    assert body.get("assessment_status") == {
        "threat": "default", "confidence": "declared", "issues": ["threat-invalid"],
    }
    assert body.get("verification_status") == "unverified"
    assert body["threat_assessment"] == "MODERATE" and body["confidence"] == 0.3
