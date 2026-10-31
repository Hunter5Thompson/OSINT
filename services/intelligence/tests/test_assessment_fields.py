"""L02 regression through the existing synthesis and legacy nodes."""

from unittest.mock import AsyncMock

import httpx
import pytest
from langchain_core.messages import AIMessage

import graph.nodes as nodes
import graph.workflow as workflow

NOTICE = (
    "Assessment-Felder konnten nicht eindeutig gelesen werden; "
    "angezeigte Standardwerte sind keine extrahierte Bewertung."
)


@pytest.mark.parametrize(
    ("report", "threat", "confidence", "invalid"),
    [
        (
            "Threat Assessment: MODERATE\nConfidence Level: low confidence\nhighway",
            "MODERATE",
            0.3,
            False,
        ),
        (
            "Threat Assessment: MODERATE (not critical)\nConfidence Level: low confidence\n"
            "There is no high confidence in this report.",
            "MODERATE",
            0.3,
            False,
        ),
        (
            "Highlights only; critical commentary and high confidence in prose.",
            "MODERATE",
            0.5,
            True,
        ),
        (
            "3. **Threat Assessment**\nHIGH\n4. **Confidence Level**\nmoderate confidence",
            "HIGH",
            0.6,
            False,
        ),
        ("Threat Assessment: ELEVATED\nConfidence Level: high confidence", "ELEVATED", 0.8, False),
        ("Threat Assessment: CRITICAL\nConfidence Level: low confidence", "CRITICAL", 0.3, False),
        (
            "Threat Assessment: HIGH\nThreat Assessment: MODERATE\n"
            "Confidence Level: low confidence",
            "MODERATE",
            0.3,
            True,
        ),
        (
            "Threat Assessment: HIGH\nConfidence Level: low confidence\n"
            "Confidence Level: high confidence",
            "HIGH",
            0.5,
            True,
        ),
        (
            "Threat Assessment: HIGHWAY\nConfidence Level: very high confidence",
            "MODERATE",
            0.5,
            True,
        ),
    ],
)
async def test_synthesis_uses_only_declared_fields(
    monkeypatch, report, threat, confidence, invalid
):
    fake = AsyncMock()
    fake.ainvoke.return_value = AIMessage(content=report)
    monkeypatch.setattr(workflow, "create_synthesis_llm", lambda: fake)

    result = await workflow.react_synthesis_node({"query": "synthetic", "messages": []})

    assert result["threat_assessment"] == threat
    assert result["confidence"] == confidence
    assert result["synthesis"].count(NOTICE) == int(invalid)
    assert result["sources_used"] == []


async def test_legacy_analyst_does_not_extract_threat_from_prose(monkeypatch):
    fake = AsyncMock()
    fake.ainvoke.return_value = AIMessage(
        content="Threat Assessment: MODERATE\nhighway, not critical"
    )
    monkeypatch.setattr(nodes, "create_analyst_llm", lambda: fake)
    result = await nodes.analyst_node({"query": "synthetic", "osint_results": []})
    assert result["threat_assessment"] == "MODERATE"


async def test_legacy_synthesis_uses_same_fields_and_missing_field_notice(monkeypatch):
    fake = AsyncMock()
    fake.ainvoke.return_value = AIMessage(content="high confidence appears in prose only")
    monkeypatch.setattr(nodes, "create_synthesis_llm", lambda: fake)
    result = await nodes.synthesis_node({"query": "synthetic", "analysis": "synthetic"})
    assert result["threat_assessment"] == "MODERATE"
    assert result["confidence"] == 0.5
    assert result["synthesis"].count(NOTICE) == 1


async def test_query_response_carries_parse_notice(monkeypatch):
    import main

    fake = AsyncMock()
    fake.ainvoke.return_value = AIMessage(content="No declared assessment fields")
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
    assert body["analysis"].count(NOTICE) == 1
    assert body["threat_assessment"] == "MODERATE" and body["confidence"] == 0.5
