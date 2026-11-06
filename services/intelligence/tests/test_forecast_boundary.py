"""Unqualified model scenario premises cannot become user-visible analysis."""

import json
from unittest.mock import AsyncMock

from langchain_core.messages import AIMessage

from agents.current_report import compose_current_report
from rag.evidence import EvidenceItem, SourceRef


async def test_forecast_uses_only_a_server_owned_unassessed_framework():
    item = EvidenceItem(
        evidence_id="ev-current",
        title="Public statement",
        excerpt="Officials said negotiations were continuing.",
        relevance_score=1,
        source=SourceRef(source_ref_id="source", source_type="web", provider="fixture"),
    )
    findings = {
        "findings": [
            {
                "passage_id": "ev-current:p0",
                "statement": "Laut Beamten liefen die Verhandlungen weiter.",
            }
        ]
    }
    model = AsyncMock()
    model.ainvoke.side_effect = [AIMessage(content=json.dumps(findings))] * 2 + [
        AIMessage(
            content=json.dumps({"checks": [{"id": "f0", "faithful": True, "reason": "Faithful"}]})
        ),
    ]
    report = await compose_current_report("Neue Angriffe auf Iran morgen?", [item], model)
    assert report.forecast_requested and report.scenario_count == 3
    assert item.excerpt in report.text
    assert "Unbewertetes Prüfraster" in report.text
    assert "keine verlässliche Zuordnung" in report.text
    schema = model.ainvoke.call_args_list[0].kwargs["response_format"]["json_schema"]["schema"]
    assert set(schema["properties"]) == {"findings"}
    assert model.ainvoke.await_count == 3


async def test_an_injected_scenario_claim_is_rejected_and_cannot_survive_correction():
    item = EvidenceItem(
        evidence_id="ev-current",
        title="Public statement",
        excerpt="Officials denied an attack order.",
        relevance_score=1,
        source=SourceRef(source_ref_id="source", source_type="web", provider="fixture"),
    )
    findings = {
        "findings": [
            {"passage_id": "ev-current:p0", "statement": "Beamte bestritten einen Angriffsbefehl."}
        ]
    }
    forbidden = "Die bereits vergangene Wahl findet erst morgen statt."
    model = AsyncMock()
    model.ainvoke.side_effect = [
        AIMessage(content=json.dumps({**findings, "scenarios": [{"condition": forbidden}]})),
        AIMessage(content=json.dumps(findings)),
        AIMessage(content=json.dumps({"checks": []})),
    ]
    report = await compose_current_report("Angriffe auf Iran morgen?", [item], model)
    assert forbidden not in report.text
    assert "Keine neuen Angriffe" in report.text
    assert "Größere Eskalation" in report.text
    assert item.excerpt in report.text
