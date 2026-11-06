"""A separate source-only check can withhold a model interpretation."""

import json
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage


async def test_rejected_or_missing_checks_never_approve_a_translation():
    from agents.source_check import check_statements

    model = AsyncMock()
    model.ainvoke.return_value = AIMessage(
        content=json.dumps(
            {
                "checks": [
                    {"id": "f0", "faithful": False, "reason": "Wrong speaker"},
                ]
            }
        )
    )
    result = await check_statements(
        [
            {
                "id": "f0",
                "original": "An analyst said Moscow agreed.",
                "translation": "Moskau gab an.",
            },
            {
                "id": "f1",
                "original": "An attack was denied.",
                "translation": "Ein Angriff wurde bestätigt.",
            },
        ],
        model,
    )
    assert result.approved == set()
    assert result.available is True


async def test_checker_failure_withholds_interpretations_without_inventing_approval():
    from agents.source_check import check_statements

    model = AsyncMock()
    model.ainvoke.side_effect = TimeoutError()
    result = await check_statements(
        [{"id": "f0", "original": "Source", "translation": "Claim"}], model
    )
    assert result.approved == set()
    assert result.available is False


async def test_only_one_explicit_positive_check_can_authorize_its_own_statement():
    from agents.source_check import check_statements

    model = AsyncMock()
    row = {"id": "f0", "faithful": True, "reason": "Faithful translation"}
    model.ainvoke.return_value = AIMessage(content=json.dumps({"checks": [row]}))
    pairs = [
        {
            "id": "f0",
            "original": "The minister denied it.",
            "translation": "Der Minister bestritt es.",
        }
    ]
    assert (await check_statements(pairs, model)).approved == {"f0"}
    model.ainvoke.return_value = AIMessage(content=json.dumps({"checks": [row, row]}))
    assert (await check_statements(pairs, model)).approved == set()


async def test_cancellation_of_source_check_propagates():
    import asyncio

    import pytest

    from agents.source_check import check_statements

    model = AsyncMock()
    model.ainvoke.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await check_statements([{"id": "f0", "original": "Source", "translation": "Claim"}], model)


@pytest.mark.parametrize("value", [1, "yes", "true"])
async def test_non_boolean_audit_result_never_approves_a_translation(value):
    from agents.source_check import check_statements

    model = AsyncMock()
    model.ainvoke.return_value = AIMessage(
        content=json.dumps(
            {"checks": [{"id": "f0", "faithful": value, "reason": "Claimed approval"}]}
        )
    )
    result = await check_statements(
        [
            {
                "id": "f0",
                "original": "An attack was denied.",
                "translation": "An attack was confirmed.",
            }
        ],
        model,
    )
    assert result.approved == set()
    assert result.available is False
