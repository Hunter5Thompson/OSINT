"""Current reports require source-bound quotations and conditional scenarios."""

import json
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage

from graph.result import PipelineFailureError
from rag.evidence import EvidenceItem, SourceRef

QUOTE = "The minister denied that an attack had been ordered."


def source():
    return EvidenceItem(
        evidence_id="ev-current",
        title="Minister statement",
        excerpt=QUOTE,
        relevance_score=1,
        source=SourceRef(source_ref_id="source", source_type="web", provider="fixture"),
    )


def draft(source_id="ev-current", quote=QUOTE):
    return {
        "findings": [
            {
                "source_id": source_id,
                "quote": quote,
                "statement": "Der Minister bestreitet einen Angriffsbefehl.",
            }
        ],
        "scenarios": [
            {
                "name": name,
                "condition": "Falls sich die öffentlich belegte Lage ändert",
                "supporting_ids": [source_id],
                "opposing_ids": [],
                "indicators": ["Neue offizielle Erklärungen prüfen"],
            }
            for name in ["Keine neuen Angriffe", "Begrenzte Schläge", "Größere Eskalation"]
        ],
        "gaps": ["Unabhängige Bestätigung fehlt."],
    }


async def test_quote_and_source_identity_survive_conditional_report():
    from agents.current_report import compose_current_report

    model = AsyncMock()
    model.ainvoke.return_value = AIMessage(content=json.dumps(draft()))
    report = (await compose_current_report("Iran nächste 48 Stunden", [source()], model)).text
    assert QUOTE in report
    assert "[ev-current]" in report
    assert "Keine neuen Angriffe" in report and "Größere Eskalation" in report
    assert "Threat Assessment: NOT_ASSESSED" in report
    assert "Confidence Level: not assessed" in report
    assert model.ainvoke.await_count == 2


@pytest.mark.parametrize(
    "payload", [draft(source_id="ev-old"), draft(quote="An attack was ordered.")]
)
async def test_old_citations_and_invented_or_reversed_quotes_fail_closed(payload):
    from agents.current_report import compose_current_report

    model = AsyncMock()
    model.ainvoke.return_value = AIMessage(content=json.dumps(payload))
    with pytest.raises(PipelineFailureError):
        await compose_current_report("Iran nächste 48 Stunden", [source()], model)


async def test_attack_forecast_cannot_omit_the_three_conditional_scenarios():
    from agents.current_report import compose_current_report

    payload = draft()
    payload["scenarios"] = []
    model = AsyncMock()
    model.ainvoke.return_value = AIMessage(content=json.dumps(payload))
    with pytest.raises(PipelineFailureError):
        await compose_current_report("Neue Angriffe in den nächsten 48 Stunden?", [source()], model)


async def test_trimming_away_a_negation_cannot_become_a_source_quote():
    from agents.current_report import compose_current_report

    model = AsyncMock()
    model.ainvoke.return_value = AIMessage(
        content=json.dumps(draft(quote="that an attack had been ordered."))
    )
    with pytest.raises(PipelineFailureError):
        await compose_current_report("Iran", [source()], model)


async def test_opposing_authors_keep_their_own_quotes_and_cannot_swap_attribution():
    from agents.current_report import compose_current_report

    denial = source()
    allegation = source().model_copy(
        update={
            "evidence_id": "ev-opponent",
            "excerpt": "The opposition said an attack was ordered.",
        }
    )
    payload = draft()
    payload["findings"].append(
        {
            "source_id": "ev-opponent",
            "quote": allegation.excerpt,
            "statement": "Die Opposition behauptet einen Angriffsbefehl.",
        }
    )
    model = AsyncMock()
    model.ainvoke.return_value = AIMessage(content=json.dumps(payload))
    report = (await compose_current_report("Iran", [denial, allegation], model)).text
    assert f"[ev-current]\n\n> {denial.excerpt}" in report
    assert f"[ev-opponent]\n\n> {allegation.excerpt}" in report
    payload["findings"][1]["source_id"] = "ev-current"
    model.ainvoke.return_value = AIMessage(content=json.dumps(payload))
    with pytest.raises(PipelineFailureError):
        await compose_current_report("Iran", [denial, allegation], model)
