from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from agents.grounded_report import compose_report
from agents.synthesis_agent import create_synthesis_llm
from config import settings
from graph.assessment import parse_assessment
from graph.result import PipelineFailureError


async def test_unknown_or_missing_citations_are_repaired_once():
    model = AsyncMock()
    model.ainvoke.side_effect = [
        AIMessage(content="Claim [ev-invented]."),
        AIMessage(content="Attributed statement [ev-known]."),
    ]
    result = await compose_report([HumanMessage(content="Evidence")], {"ev-known"}, model)
    assert result == "Attributed statement [ev-known]."
    assert model.ainvoke.await_count == 2


def test_declared_non_assessment_remains_null():
    result = parse_assessment("Threat Assessment: NOT_ASSESSED\nConfidence Level: not assessed")
    assert result.threat is None and result.confidence is None
    assert result.status == {"threat": "not_assessed", "confidence": "not_assessed", "issues": []}


async def test_archive_only_report_cannot_assess_current_threat():
    model = AsyncMock()
    model.ainvoke.side_effect = [
        AIMessage(
            content="Claim [ev-known].\nThreat Assessment: HIGH\nConfidence Level: high confidence"
        ),
        AIMessage(
            content="Source perspective [ev-known].\nThreat Assessment: NOT_ASSESSED\n"
            "Confidence Level: not assessed"
        ),
    ]
    result = await compose_report(
        [HumanMessage(content="Archive only")], {"ev-known"}, model, background_only=True
    )
    assert parse_assessment(result).threat is None
    assert model.ainvoke.await_count == 2


@pytest.mark.parametrize("text", ["No citation", "Claim [ev-invented].", ""])
async def test_unrepairable_report_is_an_explicit_failure(text):
    model = AsyncMock()
    model.ainvoke.return_value = AIMessage(content=text)
    with pytest.raises(PipelineFailureError, match="citation"):
        await compose_report([HumanMessage(content="Evidence")], {"ev-known"}, model)
    assert model.ainvoke.await_count == 2


@pytest.mark.parametrize("citation", ["`ev-known`", "ev-known", "[ev-known]"])
async def test_exact_citation_identity_accepts_and_normalizes_model_formatting(citation):
    model = AsyncMock()
    model.ainvoke.return_value = AIMessage(content=f"Source perspective ({citation}).")
    result = await compose_report([HumanMessage(content="Evidence")], {"ev-known"}, model)
    assert result == "Source perspective ([ev-known])."
    assert model.ainvoke.await_count == 2


async def test_cited_draft_is_checked_against_originals_before_publication():
    model = AsyncMock()
    model.ainvoke.side_effect = [
        AIMessage(content="Author supports the quoted view [ev-known]."),
        AIMessage(content="Author rejects the quoted view [ev-known]."),
    ]
    result = await compose_report(
        [HumanMessage(content="They say X. I disagree completely. [ev-known]")],
        {"ev-known"}, model,
    )
    assert result == "Author rejects the quoted view [ev-known]."
    checked_messages = model.ainvoke.call_args.args[0]
    assert "They say X. I disagree completely." in checked_messages[0].content
    assert "Author supports" in checked_messages[-2].content
    assert model.ainvoke.call_args.kwargs == {
        "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
        "max_tokens": 2000,
    }


async def test_truncated_revision_is_not_published_even_with_a_valid_citation():
    model = AsyncMock()
    model.ainvoke.return_value = AIMessage(
        content="Unfinished claim [ev-known]", response_metadata={"finish_reason": "length"}
    )
    with pytest.raises(PipelineFailureError, match="citation"):
        await compose_report([HumanMessage(content="Evidence")], {"ev-known"}, model)


async def test_valid_citation_does_not_hide_an_invented_bare_identity():
    model = AsyncMock()
    model.ainvoke.return_value = AIMessage(content="Claim [ev-known]. Other claim `ev-invented`.")
    with pytest.raises(PipelineFailureError, match="citation"):
        await compose_report([HumanMessage(content="Evidence")], {"ev-known"}, model)


def test_original_passages_use_base_reasoning_without_the_summary_adapter(monkeypatch):
    monkeypatch.setattr(settings, "synthesis_model", "summary-adapter")
    monkeypatch.setattr(settings, "vllm_model", "base-model")
    grounded = create_synthesis_llm(original_passages=True)
    assert grounded.model_name == "base-model"
    assert grounded.extra_body == {"chat_template_kwargs": {"enable_thinking": True}}
    assert grounded.max_tokens == 5000
    legacy = create_synthesis_llm()
    assert legacy.model_name == "summary-adapter"
    assert legacy.extra_body == {"chat_template_kwargs": {"enable_thinking": False}}
