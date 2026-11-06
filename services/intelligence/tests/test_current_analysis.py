"""Targeted repair and comparisons must retain their original evidence bindings."""

import json
from unittest.mock import AsyncMock

from langchain_core.messages import AIMessage

from agents.current_report import compose_current_report
from tests.test_current_report import draft, source
from tests.test_source_check_dimensions import check_row


def response(payload):
    return AIMessage(content=json.dumps(payload))


def pair_row(key="c0", **updates):
    return {
        "id": key,
        "comparable": "yes",
        "same_question": "no",
        "same_subject": "yes",
        "same_time": "unclear",
        "same_conditions": "no",
        "consistent": "yes",
        "evaluations_differ": "yes",
        "reason": "Different conditions or views.",
        **updates,
    }


async def test_repair_receives_actual_failure_and_rechecks_corrected_statement():
    original = "Iran plans retaliation if war resumes."
    bad = "Iran plant Vergeltung."
    good = "Iran plant Vergeltung, falls der Krieg wieder beginnt."
    payload = draft()
    payload["findings"][0]["statement"] = bad
    model = AsyncMock()
    model.ainvoke.side_effect = [
        response(payload),
        response({"checks": [check_row(conditions="changed", reason="Missing if war resumes")]}),
        response({"repairs": [{"id": "f0", "statement": good}]}),
        response(
            {
                "checks": [
                    check_row(
                        condition_quotes=["if war resumes"],
                        condition_renderings=["falls der Krieg wieder beginnt"],
                    )
                ]
            }
        ),
    ]
    report = await compose_current_report(
        "Iran", [source().model_copy(update={"excerpt": original})], model
    )
    assert good in report.text and bad not in report.text
    assert report.statement_check == "passed"
    repair_input = model.ainvoke.call_args_list[2].args[0][1].content
    assert "Missing if war resumes" in repair_input
    assert original in repair_input
    assert good in model.ainvoke.call_args_list[3].args[0][1].content


async def test_failed_repair_keeps_original_without_reviving_rejected_summary():
    payload = draft()
    model = AsyncMock()
    model.ainvoke.side_effect = [
        response(payload),
        response({"checks": [check_row(action="changed", reason="Reversed action")]}),
        TimeoutError(),
    ]
    report = await compose_current_report("Iran", [source()], model)
    assert source().excerpt in report.text
    assert payload["findings"][0]["statement"] not in report.text
    assert report.statement_check == "partial"


async def test_repair_cannot_modify_an_approved_finding_or_change_passage():
    payload = draft()
    payload["findings"].append({"passage_id": "ev-current:p1", "statement": "Talks continue."})
    item = source().model_copy(update={"excerpt": source().excerpt + "\n\nTalks continue."})
    model = AsyncMock()
    model.ainvoke.side_effect = [
        response(payload),
        response({"checks": [check_row(), check_row("f1", action="changed")]}),
        response(
            {
                "repairs": [
                    {"id": "f0", "statement": "An attack is certain."},
                    {"id": "f1", "statement": "Talks continue."},
                ]
            }
        ),
    ]
    report = await compose_current_report("Iran", [item], model)
    assert payload["findings"][0]["statement"] in report.text
    assert "An attack is certain" not in report.text
    assert report.statement_check == "partial"


async def test_source_comparison_uses_originals_and_renders_only_checked_links():
    from agents.source_comparison import compare_sources

    readings = [
        {
            "id": "f0",
            "source_id": "ev-a",
            "original": "Talks continue.",
            "statement": "Gespräche dauern an.",
            "published_at": "2026-11-06",
            "lineage": "agency:a",
        },
        {
            "id": "f1",
            "source_id": "ev-b",
            "original": "Retaliation is planned if war resumes.",
            "statement": "Vergeltung ist geplant, falls der Krieg wieder beginnt.",
            "published_at": "2026-11-06",
            "lineage": "agency:b",
        },
    ]
    statement = "Unterschiedliche Bedingungen oder Gegenstände"
    model = AsyncMock()
    model.ainvoke.side_effect = [
        response({"comparisons": [{"finding_ids": ["f0", "f1"], "relation": "compatible"}]}),
        response({"pairs": [pair_row()]}),
    ]
    result = await compare_sources("Iran", readings, model, as_of="2026-11-06")
    assert result.count == 1
    assert statement in result.text and "[ev-a]" in result.text and "[ev-b]" in result.text
    audit_input = model.ainvoke.call_args_list[1].args[0][1].content
    assert readings[0]["original"] in audit_input and readings[1]["original"] in audit_input


async def test_unknown_duplicate_or_single_finding_links_cannot_authorize_a_comparison():
    from agents.source_comparison import compare_sources

    readings = [
        {"id": "f0", "source_id": "ev-a", "original": "A", "statement": "A"},
        {"id": "f1", "source_id": "ev-b", "original": "B", "statement": "B"},
    ]
    for ids in [["f0", "missing"], ["f0", "f0"], ["f0"]]:
        model = AsyncMock()
        model.ainvoke.return_value = response(
            {"comparisons": [{"finding_ids": ids, "relation": "compatible"}]}
        )
        result = await compare_sources("Q", readings, model)
        assert result.count == 0 and "Unsupported comparison" not in result.text


async def test_comparison_failure_does_not_remove_sourced_findings():
    payload = draft()
    payload["findings"].append(
        {"passage_id": "ev-other:p0", "statement": "Die Opposition widerspricht."}
    )
    item = source().model_copy(
        update={"evidence_id": "ev-other", "excerpt": "The opposition disagrees."}
    )
    model = AsyncMock()
    model.ainvoke.side_effect = [
        response(payload),
        response({"checks": [check_row(), check_row("f1")]}),
        TimeoutError(),
    ]
    report = await compose_current_report("Iran", [source(), item], model)
    assert report.finding_count == 2
    assert payload["findings"][0]["statement"] in report.text
    assert report.comparison_check == "unavailable"
    assert "Quellenvergleich" in report.text


async def test_analysis_budget_keeps_approved_findings_when_optional_comparison_stalls(monkeypatch):
    import asyncio

    import agents.current_report as report_module

    payload = draft()
    payload["findings"].append({"passage_id": "ev-other:p0", "statement": "Gespräche dauern an."})
    item = source().model_copy(update={"evidence_id": "ev-other", "excerpt": "Talks continue."})
    model = AsyncMock()
    model.ainvoke.side_effect = [
        response(payload),
        response({"checks": [check_row(), check_row("f1")]}),
    ]

    async def stalled(*args, **kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(report_module, "compare_sources", stalled)
    monkeypatch.setattr(report_module, "ANALYSIS_BUDGET_S", 0.01, raising=False)
    report = await asyncio.wait_for(compose_current_report("Iran", [source(), item], model), 0.5)
    assert report.finding_count == 2
    assert payload["findings"][0]["statement"] in report.text
    assert report.comparison_check == "unavailable"


async def test_cancellation_is_not_reported_as_a_completed_analysis():
    import asyncio

    import pytest

    model = AsyncMock()
    model.ainvoke.side_effect = [response(draft()), asyncio.CancelledError()]
    with pytest.raises(asyncio.CancelledError):
        await compose_current_report("Iran", [source()], model)


async def test_different_perspectives_in_the_same_article_can_be_compared():
    from agents.source_comparison import compare_sources

    readings = [
        {
            "id": "f0",
            "source_id": "ev-a",
            "passage_id": "ev-a:p0",
            "original": "Iranian sources fear strikes.",
            "statement": "Iranische Quellen fürchten Schläge.",
        },
        {
            "id": "f1",
            "source_id": "ev-a",
            "passage_id": "ev-a:p1",
            "original": "Gulf sources see a deal as more likely.",
            "statement": "Golf-Quellen halten ein Abkommen für wahrscheinlicher.",
        },
    ]
    model = AsyncMock()
    model.ainvoke.side_effect = [
        response(
            {"comparisons": [{"finding_ids": ["f0", "f1"], "relation": "different_assessments"}]}
        ),
        response({"pairs": [pair_row(same_question="yes")]}),
    ]
    result = await compare_sources("Iran", readings, model)
    assert result.count == 1
    assert "Unterschiedliche Einschätzungen" in result.text
    assert "derselben Quelle" in result.text


async def test_comparison_schema_has_no_channel_for_invented_causal_prose():
    from agents.source_comparison import compare_sources

    model = AsyncMock()
    model.ainvoke.return_value = response(
        {
            "comparisons": [
                {
                    "finding_ids": ["f0", "f1"],
                    "relation": "compatible",
                    "statement": "A caused B on an invented date.",
                }
            ]
        }
    )
    result = await compare_sources(
        "Q",
        [
            {"id": "f0", "source_id": "ev-a", "original": "A", "statement": "A"},
            {"id": "f1", "source_id": "ev-b", "original": "B", "statement": "B"},
        ],
        model,
    )
    assert result.count == 0
    assert "A caused B" not in result.text


async def test_relation_reviewer_does_not_see_or_blindly_accept_proposed_relationship():
    from agents.source_comparison import compare_sources

    model = AsyncMock()
    model.ainvoke.side_effect = [
        response({"comparisons": [{"finding_ids": ["f0", "f1"], "relation": "contradiction"}]}),
        response({"pairs": [pair_row(evaluations_differ="no")]}),
    ]
    readings = [
        {
            "id": "f0",
            "source_id": "ev-a",
            "original": "Talks continue.",
            "statement": "Talks continue.",
        },
        {
            "id": "f1",
            "source_id": "ev-b",
            "original": "Retaliation if attacked.",
            "statement": "Retaliation if attacked.",
        },
    ]
    result = await compare_sources("Q", readings, model)
    assert result.count == 1 and result.status == "partial"
    assert "Widersprechende Angaben" not in result.text
    audit_input = model.ainvoke.call_args_list[1].args[0][1].content
    assert "contradiction" not in audit_input
    assert "Talks continue." in audit_input


async def test_readiness_and_likelihood_are_not_competing_assessments_of_the_same_question():
    from agents.source_comparison import RELATIONS, compare_sources

    model = AsyncMock()
    model.ainvoke.side_effect = [
        response(
            {"comparisons": [{"finding_ids": ["f0", "f1"], "relation": "different_assessments"}]}
        ),
        response({"pairs": [pair_row(same_question="no", evaluations_differ="yes")]}),
    ]
    result = await compare_sources(
        "Outlook",
        [
            {
                "id": "f0",
                "source_id": "ev-a",
                "original": "We are ready if necessary.",
                "statement": "Wir sind bereit, falls nötig.",
            },
            {
                "id": "f1",
                "source_id": "ev-b",
                "original": "A full attack is less likely.",
                "statement": "Ein umfassender Angriff ist weniger wahrscheinlich.",
            },
        ],
        model,
    )
    assert RELATIONS["different_assessments"] not in result.text
    assert RELATIONS["compatible"] in result.text
    assert result.count == 1 and result.status == "partial"


async def test_empty_pair_selection_recovers_only_a_supported_relation():
    from agents.source_comparison import compare_sources

    readings = [
        {
            "id": "f0",
            "source_id": "ev-a",
            "original": "Talks continue.",
            "statement": "Talks continue.",
        },
        {
            "id": "f1",
            "source_id": "ev-b",
            "original": "Retaliation if attacked.",
            "statement": "Retaliation if attacked.",
        },
    ]
    for comparable, count in [("yes", 1), ("no", 0)]:
        model = AsyncMock()
        model.ainvoke.side_effect = [
            response({"comparisons": []}),
            response({"pairs": [pair_row(comparable=comparable, evaluations_differ="no")]}),
        ]
        result = await compare_sources("Q", readings, model)
        assert result.count == count


async def test_different_subjects_cannot_authorize_agreement_or_contradiction():
    from agents.source_comparison import _check_relations

    model = AsyncMock()
    model.ainvoke.return_value = response({"pairs": [pair_row(
        same_subject="no", same_question="yes", same_time="yes",
        same_conditions="yes", evaluations_differ="no",
    )]})
    allowed = await _check_relations([{"id": "c0", "originals": [
        "The northern dock is closed.", "The southern dock is open.",
    ]}], model)
    assert allowed == {"c0": {"compatible"}}
