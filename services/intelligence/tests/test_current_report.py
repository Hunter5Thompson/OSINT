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


def draft(source_id="ev-current"):
    return {
        "findings": [
            {
                "passage_id": f"{source_id}:p0",
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


async def test_unknown_or_old_passage_ids_fail_closed():
    from agents.current_report import compose_current_report

    model = AsyncMock()
    model.ainvoke.return_value = AIMessage(content=json.dumps(draft(source_id="ev-old")))
    with pytest.raises(PipelineFailureError):
        await compose_current_report("Iran", [source()], model)


async def test_attack_forecast_cannot_omit_the_three_conditional_scenarios():
    from agents.current_report import compose_current_report

    payload = draft()
    payload["scenarios"] = []
    model = AsyncMock()
    model.ainvoke.return_value = AIMessage(content=json.dumps(payload))
    with pytest.raises(PipelineFailureError):
        await compose_current_report("Neue Angriffe in den nächsten 48 Stunden?", [source()], model)


async def test_opposing_authors_keep_their_own_passages():
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
            "passage_id": "ev-opponent:p0",
            "statement": "Die Opposition behauptet einen Angriffsbefehl.",
        }
    )
    model = AsyncMock()
    model.ainvoke.return_value = AIMessage(content=json.dumps(payload))
    report = (await compose_current_report("Iran", [denial, allegation], model)).text
    assert "[ev-current]" in report and f"> {denial.excerpt}" in report
    assert "[ev-opponent]" in report and f"> {allegation.excerpt}" in report


@pytest.mark.parametrize(
    "text",
    [
        "Officials denied that a U.S. attack had been ordered.",
        "Officials explicitly rejected this claim: an attack has been ordered.",
        "Officials explicitly rejected this claim — an attack has been ordered.",
    ],
)
async def test_passage_selection_preserves_negation_abbreviations_and_complete_paragraph(text):
    from agents.current_report import compose_current_report

    item = source().model_copy(update={"excerpt": text})
    model = AsyncMock()
    model.ainvoke.return_value = AIMessage(content=json.dumps(draft()))
    report = await compose_current_report("Iran", [item], model)
    assert "> " + text in report.text
    prompt = model.ainvoke.call_args.args[0][1].content
    assert text in prompt and "ev-current:p0" in prompt


async def test_model_cannot_replace_a_selected_passage_with_its_own_quote():
    from agents.current_report import compose_current_report

    payload = draft()
    payload["findings"][0]["quote"] = "an attack has been ordered."
    model = AsyncMock()
    model.ainvoke.return_value = AIMessage(content=json.dumps(payload))
    with pytest.raises(PipelineFailureError):
        await compose_current_report("Iran", [source()], model)


async def test_scenario_can_reference_an_existing_specific_passage():
    from agents.current_report import compose_current_report

    payload = draft()
    payload["scenarios"][0]["supporting_ids"] = ["ev-current:p0"]
    model = AsyncMock()
    model.ainvoke.return_value = AIMessage(content=json.dumps(payload))
    report = await compose_current_report("Iran nächste 48 Stunden", [source()], model)
    assert "Stützende Angaben: [ev-current]." in report.text
    payload["scenarios"][0]["supporting_ids"] = ["ev-current:p999"]
    model.ainvoke.return_value = AIMessage(content=json.dumps(payload))
    with pytest.raises(PipelineFailureError):
        await compose_current_report("Iran nächste 48 Stunden", [source()], model)


async def test_irrelevant_originals_do_not_force_a_factual_finding_or_forecast():
    from agents.current_report import compose_current_report

    model = AsyncMock()
    model.ainvoke.return_value = AIMessage(
        content=json.dumps(
            {
                "findings": [],
                "scenarios": [],
                "gaps": ["Keine thematisch tragfähige Originalpassage."],
            }
        )
    )
    report = await compose_current_report(
        "Angriffe auf Iran in den nächsten 48 Stunden?", [source()], model
    )
    assert report.finding_count == 0
    assert "Keine thematisch tragfähige Originalpassage" in report.text


async def test_report_uses_the_server_clock_and_bounded_source_checks():
    from agents.current_report import compose_current_report

    model = AsyncMock()
    model.ainvoke.return_value = AIMessage(content=json.dumps(draft()))
    await compose_current_report("Iran", [source()], model, as_of="2026-11-06T18:00:00+00:00")
    first, check = model.ainvoke.call_args_list
    assert "2026-11-06T18:00:00+00:00" in first.args[0][1].content
    assert first.kwargs["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False
    assert first.kwargs["max_tokens"] <= 4000
    assert check.kwargs["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False


async def test_a_current_situation_question_does_not_gain_unrequested_scenarios():
    from agents.current_report import compose_current_report

    model = AsyncMock()
    model.ainvoke.return_value = AIMessage(content=json.dumps(draft()))
    report = await compose_current_report(
        "Aktuelle Ergebnisse der US-Zwischenwahlen?", [source()], model
    )
    assert report.scenario_count == 0
    assert "Bedingte Szenarien" not in report.text
