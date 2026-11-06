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


async def test_empty_forecast_report_retains_qualification_gap_in_workflow(monkeypatch):
    from pathlib import Path

    import graph.workflow as workflow
    from agents.current_report import RenderedCurrentReport
    from rag.evidence import RetrievalProvenance, pack_with_lineage

    fixture = json.loads(
        (Path(__file__).resolve().parents[3] / "tests/fixtures/current-research.json").read_text()
    )
    raw = fixture["evidence_summary"][0]
    item = EvidenceItem(
        evidence_id=raw["evidence_id"],
        title=raw["title"],
        excerpt=raw["excerpt"],
        relevance_score=1,
        source=SourceRef(
            **{
                key: raw[key]
                for key in ("source_ref_id", "source_type", "provider", "published_at")
            }
        ),
        retrieval=RetrievalProvenance.model_validate(raw["retrieval"]),
    )
    pack, artifact = pack_with_lineage([item], budget=3000)
    monkeypatch.setattr(workflow, "create_synthesis_llm", lambda **kwargs: AsyncMock())
    monkeypatch.setattr(
        workflow,
        "compose_current_report",
        AsyncMock(
            return_value=RenderedCurrentReport(
                text="Keine passende Lagepassage gewählt; Prognose offen.",
                finding_count=0,
                scenario_count=0,
                forecast_requested=True,
            )
        ),
    )
    result = await workflow.react_synthesis_node(
        {
            "query": "Neue Angriffe morgen?",
            "messages": [],
            "current_evidence_pack": pack,
            "current_evidence_artifact": artifact,
            "research_coverage": fixture["research_coverage"],
        }
    )
    assert result["research_coverage"]["forecast"] == "not_assessed"
    assert "forecast_details_not_qualified" in result["research_coverage"]["gaps"]
    assert result["research_coverage"]["situation"] == "insufficient_evidence"
