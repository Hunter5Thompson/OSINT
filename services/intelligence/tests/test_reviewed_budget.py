import json

from langchain_core.messages import ToolMessage

from graph.workflow import _budget_research_segments, _compact_tool_messages
from rag.evidence import pack_with_lineage, to_evidence_item
from tests.test_reviewed_evidence_contract import PAYLOADS


def test_compaction_never_splits_claim_from_qualification():
    item = to_evidence_item(next(p for p in PAYLOADS if p["review"]["claim_id"] == "C060"))
    text, artifact = pack_with_lineage([item], budget=18000)
    result = _compact_tool_messages(
        [ToolMessage(content=text, artifact=artifact, tool_call_id="1")]
    )
    assert result[0].artifact, "a normal single reviewed claim must fit the research prompt"
    meta = json.loads(result[0].content.splitlines()[0].removeprefix("[EVIDENCE] "))
    assert item.review.qualification_note == meta["review"]["qualification_note"]
    assert "[truncated" not in result[0].content


def test_repeated_claim_does_not_consume_budget_again():
    items = [to_evidence_item(p) for p in PAYLOADS if p["review"]["claim_id"] in ("C060", "C061")]
    first, second = [pack_with_lineage([item], budget=18000) for item in items]
    text, artifact = _budget_research_segments([first] * 10 + [second], budget=18000)
    assert len(artifact) == 2
    assert all(item.evidence_id in text for item in items)
