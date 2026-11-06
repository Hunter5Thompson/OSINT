"""Current reports require source-bound quotations and conditional scenarios."""

import json
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage

from graph.result import PipelineFailureError
from rag.evidence import EvidenceItem, SourceRef
from tests.test_source_check_dimensions import check_row

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
        ]
    }


async def test_quote_and_source_identity_survive_conditional_report():
    from agents.current_report import compose_current_report

    model = AsyncMock()
    model.ainvoke.return_value = AIMessage(content=json.dumps(draft()))
    report = (
        await compose_current_report("Angriffe auf Iran nächste 48 Stunden", [source()], model)
    ).text
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
    prompt = model.ainvoke.call_args_list[0].args[0][1].content
    assert text in prompt and "ev-current:p0" in prompt


async def test_model_cannot_replace_a_selected_passage_with_its_own_quote():
    from agents.current_report import compose_current_report

    payload = draft()
    payload["findings"][0]["quote"] = "an attack has been ordered."
    model = AsyncMock()
    model.ainvoke.return_value = AIMessage(content=json.dumps(payload))
    with pytest.raises(PipelineFailureError):
        await compose_current_report("Iran", [source()], model)


async def test_irrelevant_originals_do_not_force_a_factual_finding_or_forecast():
    from agents.current_report import compose_current_report

    model = AsyncMock()
    model.ainvoke.return_value = AIMessage(
        content=json.dumps(
            {
                "findings": [],
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
    first, check = model.ainvoke.call_args_list[:2]
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


@pytest.mark.parametrize(
    "question,expected",
    [
        ("Welche Angriffe gab es in den letzten 48 Stunden?", 0),
        ("Gibt es morgen neue Angriffe auf Iran?", 3),
    ],
)
async def test_a_time_span_is_distinct_from_a_future_request(question, expected):
    from agents.current_report import compose_current_report

    model = AsyncMock()
    model.ainvoke.return_value = AIMessage(content=json.dumps(draft()))
    report = await compose_current_report(question, [source()], model)
    assert report.scenario_count == expected


async def test_failed_source_check_preserves_original_and_withholds_interpretation():
    from agents.current_report import compose_current_report

    payload = draft()
    payload["findings"][0]["statement"] = "Der Minister hat den Angriff befohlen."
    model = AsyncMock()
    model.ainvoke.side_effect = [AIMessage(content=json.dumps(payload))] + [
        AIMessage(
            content=json.dumps({"checks": [check_row(polarity="changed", reason="Negation")]})
        ),
    ]
    report = await compose_current_report("Iran", [source()], model)
    assert QUOTE in report.text
    assert "Der Minister hat den Angriff befohlen." not in report.text
    assert "zurückgehalten" in report.text
    assert report.statement_check == "partial"


@pytest.mark.parametrize(
    "boilerplate",
    [
        "## White House denies ministers will leave their jobs",
        "TOP STORIES\n * [Election rumors](https://example.org/a)\n * [Unrelated story](https://example.org/b)",
    ],
)
async def test_headings_and_link_directories_are_not_selectable_original_findings(boilerplate):
    from agents.current_report import compose_current_report

    item = source().model_copy(update={"excerpt": boilerplate + "\n\n" + QUOTE})
    model = AsyncMock()
    payload = draft()
    payload["findings"][0]["passage_id"] = "ev-current:p1"
    model.ainvoke.return_value = AIMessage(content=json.dumps(payload))
    report = await compose_current_report("Iran", [item], model)
    prompt = json.loads(model.ainvoke.call_args_list[0].args[0][1].content)
    assert prompt["sources"][0]["passages"] == [{"passage_id": "ev-current:p1", "text": QUOTE}]
    assert boilerplate not in report.text
    assert QUOTE in report.text


async def test_model_gap_claims_do_not_escape_the_source_check_as_report_facts():
    from agents.current_report import compose_current_report

    payload = draft()
    payload["gaps"] = ["All sources dated 2026 are fictional."]
    model = AsyncMock()
    model.ainvoke.return_value = AIMessage(content=json.dumps(payload))
    with pytest.raises(PipelineFailureError):
        await compose_current_report("Iran", [source()], model)


async def test_report_limits_are_server_owned_and_need_no_model_gap_prose():
    from agents.current_report import compose_current_report

    model = AsyncMock()
    model.ainvoke.return_value = AIMessage(content=json.dumps(draft()))
    report = await compose_current_report("Iran", [source()], model)
    assert "Keine externe Faktenprüfung" in report.text
    assert QUOTE in report.text


@pytest.mark.parametrize(
    "question,scenario_count",
    [
        ("Neue Angriffe auf Iran morgen?", 3),
        ("Wie entwickelt sich die Lage morgen?", 0),
    ],
)
async def test_open_forecast_does_not_discard_an_available_current_situation(
    question, scenario_count
):
    from agents.current_report import compose_current_report

    model = AsyncMock()
    empty = AIMessage(content=json.dumps({"findings": []}))
    model.ainvoke.side_effect = [
        empty,
        AIMessage(content=json.dumps({"findings": draft()["findings"]})),
        AIMessage(
            content=json.dumps(
                {
                    "checks": [
                        check_row(reason="Faithful denial"),
                    ]
                }
            )
        ),
    ]
    report = await compose_current_report(question, [source()], model)
    assert report.finding_count == 1
    assert QUOTE in report.text
    assert draft()["findings"][0]["statement"] in report.text
    assert report.scenario_count == scenario_count
    assert report.forecast_requested is True
    if scenario_count:
        assert "Unbewertetes Prüfraster" in report.text
    assert "Stützende Angaben" not in report.text


async def test_unavailable_source_reader_cannot_invent_a_recovered_finding():
    from agents.current_report import compose_current_report

    model = AsyncMock()
    empty = AIMessage(content=json.dumps({"findings": []}))
    model.ainvoke.side_effect = [empty, TimeoutError()]
    report = await compose_current_report("Iran morgen?", [source()], model)
    assert report.finding_count == 0
    assert QUOTE not in report.text
    assert "Keine thematisch tragfähige Originalpassage" in report.text
