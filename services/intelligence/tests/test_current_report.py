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
    assert model.ainvoke.await_count == 4


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


async def test_scenario_can_reference_an_existing_specific_passage():
    from agents.current_report import compose_current_report

    payload = draft()
    payload["scenarios"][0]["supporting_ids"] = ["ev-current:p0"]
    model = AsyncMock()
    model.ainvoke.return_value = AIMessage(content=json.dumps(payload))
    model.ainvoke.side_effect = [
        AIMessage(content=json.dumps(payload)),
        AIMessage(content=json.dumps(payload)),
        AIMessage(content=json.dumps({"checks": []})),
        AIMessage(
            content=json.dumps(
                {
                    "checks": [
                        {
                            "id": f"s{index}",
                            "faithful": True,
                            "reason": "Conditional and source-grounded",
                        }
                        for index in range(3)
                    ]
                }
            )
        ),
    ]
    report = await compose_current_report("Iran nächste 48 Stunden", [source()], model)
    assert "Stützende Angaben: [ev-current]." in report.text
    payload["scenarios"][0]["supporting_ids"] = ["ev-current:p999"]
    model.ainvoke.side_effect = None
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


async def test_attack_scenario_structure_is_constrained_at_the_model_boundary():
    from agents.current_report import compose_current_report

    model = AsyncMock()
    model.ainvoke.return_value = AIMessage(content=json.dumps(draft()))
    await compose_current_report(
        "Neue Angriffe auf Iran in den nächsten 48 Stunden?", [source()], model
    )
    contract = model.ainvoke.call_args_list[0].kwargs["response_format"]
    assert contract["type"] == "json_schema"
    schema = contract["json_schema"]["schema"]
    assert schema["anyOf"][0]["properties"]["scenarios"]["minItems"] == 3
    assert schema["$defs"]["Finding"]["properties"]["passage_id"]["enum"] == ["ev-current:p0"]


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
    model.ainvoke.side_effect = [AIMessage(content=json.dumps(payload))] * 2 + [
        AIMessage(
            content=json.dumps({"checks": [{"id": "f0", "faithful": False, "reason": "Negation"}]})
        ),
    ]
    report = await compose_current_report("Iran", [source()], model)
    assert QUOTE in report.text
    assert "Der Minister hat den Angriff befohlen." not in report.text
    assert "zurückgehalten" in report.text
    assert report.statement_check == "partial"


async def test_scenario_premise_rejection_preserves_findings_but_withholds_unsupported_details():
    from agents.current_report import compose_current_report

    payload = draft()
    payload["scenarios"][0]["condition"] = "Iran erfüllt die sieben eigenen Forderungen."
    payload["scenarios"][0]["indicators"] = ["Iran erklärt alle eigenen Forderungen erfüllt."]
    model = AsyncMock()
    model.ainvoke.side_effect = [AIMessage(content=json.dumps(payload))] * 2 + [
        AIMessage(
            content=json.dumps(
                {
                    "checks": [
                        {"id": "f0", "faithful": True, "reason": "Accurate"},
                    ]
                }
            )
        ),
        AIMessage(
            content=json.dumps(
                {
                    "checks": [
                        {"id": "s0", "faithful": False, "reason": "Wrong actor"},
                        {"id": "s1", "faithful": True, "reason": "Conditional"},
                        {"id": "s2", "faithful": True, "reason": "Conditional"},
                    ]
                }
            )
        ),
    ]
    report = await compose_current_report("Angriffe auf Iran morgen?", [source()], model)
    assert QUOTE in report.text
    assert payload["findings"][0]["statement"] in report.text
    assert payload["scenarios"][0]["condition"] not in report.text
    assert payload["scenarios"][0]["indicators"][0] not in report.text
    assert "Keine neuen Angriffe" in report.text
    assert "Szenariodetails nach Quellenprüfung zurückgehalten" in report.text
    assert report.scenario_check == "partial"
    audit_input = model.ainvoke.call_args_list[3].args[0][1].content
    assert QUOTE in audit_input
    assert payload["scenarios"][0]["condition"] in audit_input


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


async def test_rejected_free_scenario_title_cannot_leak_a_factual_claim():
    from agents.current_report import compose_current_report

    payload = draft()
    payload["scenarios"] = [payload["scenarios"][0]]
    payload["scenarios"][0]["name"] = "Der Minister hat den Angriff bestätigt"
    model = AsyncMock()
    model.ainvoke.side_effect = [AIMessage(content=json.dumps(payload))] * 2 + [
        AIMessage(content=json.dumps({"checks": []})),
        AIMessage(
            content=json.dumps(
                {
                    "checks": [
                        {"id": "s0", "faithful": False, "reason": "Unsupported title"},
                    ]
                }
            )
        ),
    ]
    report = await compose_current_report("Wie entwickelt sich die Lage morgen?", [source()], model)
    assert payload["scenarios"][0]["name"] not in report.text
    assert "Szenario 1 · nicht bewertet" in report.text


async def test_open_forecast_does_not_discard_an_available_current_situation():
    from agents.current_report import compose_current_report

    model = AsyncMock()
    empty = AIMessage(content=json.dumps({"findings": [], "scenarios": []}))
    model.ainvoke.side_effect = [
        empty,
        empty,
        AIMessage(content=json.dumps({"findings": draft()["findings"]})),
        AIMessage(
            content=json.dumps(
                {
                    "checks": [
                        {"id": "f0", "faithful": True, "reason": "Faithful denial"},
                    ]
                }
            )
        ),
    ]
    report = await compose_current_report("Neue Angriffe auf Iran morgen?", [source()], model)
    assert report.finding_count == 1
    assert QUOTE in report.text
    assert draft()["findings"][0]["statement"] in report.text
    assert report.scenario_count == 3
    assert "Szenariodetails" in report.text
    assert report.scenario_check == "partial"
    assert "Stützende Angaben" not in report.text


async def test_unavailable_source_reader_cannot_invent_a_recovered_finding():
    from agents.current_report import compose_current_report

    model = AsyncMock()
    empty = AIMessage(content=json.dumps({"findings": [], "scenarios": []}))
    model.ainvoke.side_effect = [empty, empty, TimeoutError()]
    report = await compose_current_report("Iran morgen?", [source()], model)
    assert report.finding_count == 0
    assert QUOTE not in report.text
    assert "Keine thematisch tragfähige Originalpassage" in report.text
