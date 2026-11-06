"""Frozen 47-claim readback: identity and review survive the actual prompt boundary."""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, ToolMessage

import graph.workflow as workflow
from rag.evidence import evidence_items_from_artifact, pack_with_lineage, to_evidence_item

PAYLOADS = json.loads(
    (Path(__file__).parents[3] / "tests/fixtures/reviewed-claims-47.json").read_text()
)


@pytest.mark.parametrize("payload", PAYLOADS, ids=lambda p: p["review"]["candidate_id"])
async def test_review_roundtrip_to_prompt_and_public_citation(monkeypatch, payload):
    item = to_evidence_item(payload)
    assert item.review.candidate_id == payload["review"]["candidate_id"]
    assert item.excerpt == payload["content"]
    pack, artifact = pack_with_lineage([item], budget=18000)
    assert evidence_items_from_artifact(artifact) == [item]
    llm = AsyncMock()
    llm.ainvoke.return_value = AIMessage(
        content=f"Belegt [{item.evidence_id}].\nThreat Assessment: MODERATE\n"
        "Confidence Level: low confidence"
    )
    monkeypatch.setattr(workflow, "create_synthesis_llm", lambda: llm)
    result = await workflow.react_synthesis_node(
        {
            "query": "test",
            "messages": [ToolMessage(content=pack, artifact=artifact, tool_call_id="fixture")],
        }
    )
    prompt = llm.ainvoke.call_args.args[0][-1].content
    header = next(line for line in prompt.splitlines() if line.startswith("[EVIDENCE] "))
    meta = json.loads(header.removeprefix("[EVIDENCE] "))
    public = result["evidence_summary"][0]
    assert meta["review"] == public["review"] == item.review.model_dump(mode="json")
    assert public["evidence_id"] == item.evidence_id
    assert item.evidence_id in result["synthesis"]
    for before, after in zip(
        payload["review"]["evidence"], public["review"]["evidence"], strict=True
    ):
        for key in before:
            assert after[key] == before[key]
    assert payload["review"]["qualification_note"] == public["review"]["qualification_note"]


def test_same_notebook_different_claims_remain_separate():
    payloads = [p for p in PAYLOADS if p["review"]["claim_id"] in ("C048", "C060", "C061")]
    items = [to_evidence_item(p) for p in payloads]
    assert len({x.source.source_ref_id for x in items}) == 1
    assert len({x.evidence_id for x in items}) == 3
    _, artifacts = pack_with_lineage(items, budget=18000)
    assert len(artifacts) == 3


def test_short_claim_exception_requires_matching_reviewed_notebook_statement():
    from rag.corpus_policy import validate_lane

    short = next(p for p in PAYLOADS if p["review"]["claim_id"] == "C019")
    assert validate_lane([{**short, "score": 1.0}], "analysis")
    assert not validate_lane([{**short, "review": None, "score": 1.0}], "analysis")
    assert not validate_lane(
        [{**short, "content": "Different short claim.", "score": 1.0}], "analysis"
    )
    assert not validate_lane([{**short, "source_type": "rss", "score": 1.0}], "analysis")
