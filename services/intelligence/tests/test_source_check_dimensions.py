"""Regression contracts for source meaning and quote-bound condition checks."""

import json
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage

from agents.source_check import check_statements


def check_row(key="f0", **updates):
    return {
        "id": key,
        "attribution": "preserved",
        "action": "preserved",
        "polarity": "preserved",
        "conditions": "preserved",
        "modality": "preserved",
        "time": "preserved",
        "inference": "preserved",
        "condition_quotes": [],
        "condition_renderings": [],
        "reason": "Meaning preserved.",
        **updates,
    }


PAIRS = [
    {
        "id": "f0",
        "original": "Iran is planning wider retaliation if war resumes.",
        "translation": "Iran plant breitere Vergeltung, falls der Krieg wieder beginnt.",
    }
]


@pytest.mark.parametrize(
    "dimension",
    ["attribution", "action", "polarity", "conditions", "modality", "time", "inference"],
)
async def test_a_single_changed_dimension_withholds_and_explains(dimension):
    model = AsyncMock()
    model.ainvoke.return_value = AIMessage(
        content=json.dumps(
            {
                "checks": [
                    check_row(**{dimension: "changed", "reason": "The condition was dropped."})
                ],
            }
        )
    )
    result = await check_statements(PAIRS, model)
    assert result.available
    assert result.approved == set()
    assert dimension in result.feedback["f0"]
    assert "The condition was dropped" in result.feedback["f0"]


async def test_preserved_condition_requires_real_quotes_on_both_sides():
    model = AsyncMock()
    row = check_row(
        condition_quotes=["if war resumes"], condition_renderings=["falls der Krieg wieder beginnt"]
    )
    model.ainvoke.return_value = AIMessage(content=json.dumps({"checks": [row]}))
    assert (await check_statements(PAIRS, model)).approved == {"f0"}
    missing = [{**PAIRS[0], "translation": "Iran plant breitere Vergeltung."}]
    result = await check_statements(missing, model)
    assert not result.approved  # Even a positive model verdict cannot invent a span.
    assert "f0" in result.feedback


async def test_unpaired_or_fabricated_condition_evidence_cannot_approve():
    model = AsyncMock()
    for original, translation in [
        (["if peace resumes"], ["falls der Krieg wieder beginnt"]),
        (["if war resumes"], []),
        ([""], [""]),
    ]:
        model.ainvoke.return_value = AIMessage(
            content=json.dumps(
                {"checks": [check_row(condition_quotes=original, condition_renderings=translation)]}
            )
        )
        assert not (await check_statements(PAIRS, model)).approved


async def test_old_blanket_approval_is_not_a_dimensional_check():
    model = AsyncMock()
    model.ainvoke.return_value = AIMessage(
        content=json.dumps({"checks": [{"id": "f0", "faithful": True, "reason": "Looks good"}]})
    )
    result = await check_statements(PAIRS, model)
    assert not result.approved
    assert not result.available


async def test_invisible_extraction_formatting_does_not_invalidate_correct_quotes():
    model = AsyncMock()
    model.ainvoke.return_value = AIMessage(
        content=json.dumps(
            {
                "checks": [
                    check_row(
                        condition_quotes=["if war resumes"],
                        condition_renderings=["falls der Krieg wieder beginnt"],
                    )
                ]
            }
        )
    )
    pairs = [{**PAIRS[0], "original": "Iran plans retaliation if\u200b war\nresumes."}]
    assert (await check_statements(pairs, model)).approved == {"f0"}


async def test_positive_model_check_cannot_release_a_decoder_truncated_sentence():
    model = AsyncMock()
    model.ainvoke.return_value = AIMessage(content=json.dumps({"checks": [check_row()]}))
    result = await check_statements([{
        "id": "f0", "original": "Talks continue, the minister said.",
        "translation": "Die Gespräche gehen weiter, weil der",
    }], model)
    assert not result.approved
    assert "incomplete" in result.feedback["f0"]
