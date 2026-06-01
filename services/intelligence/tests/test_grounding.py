# services/intelligence/tests/test_grounding.py
import pytest
from pydantic import ValidationError

from main import GroundingEvidenceItem, QueryRequest
from rag.evidence import format_evidence_pack, parse_evidence_refs, to_evidence_item


def test_query_request_bounds_and_allowlist():
    QueryRequest(
        query="q",
        grounding_context="ctx",
        grounding_evidence=[
            GroundingEvidenceItem(
                source_type="dataset",
                provider="odin-country-almanac",
                doc_id="d1",
                title="t",
                content="c",
            )
        ],
    )
    with pytest.raises(ValidationError):
        QueryRequest(query="q", grounding_context="x" * 4001)
    with pytest.raises(ValidationError):  # source_type not in allowlist
        GroundingEvidenceItem(
            source_type="rss", provider="odin-live-signal", doc_id="d", title="t", content="c"
        )
    with pytest.raises(ValidationError):  # provider not in allowlist
        GroundingEvidenceItem(
            source_type="dataset", provider="evil", doc_id="d", title="t", content="c"
        )
    with pytest.raises(ValidationError):  # content per-field bound
        GroundingEvidenceItem(
            source_type="dataset",
            provider="odin-live-signal",
            doc_id="d",
            title="t",
            content="c" * 2001,
        )
    with pytest.raises(ValidationError):  # >6 evidence items
        ok = GroundingEvidenceItem(
            source_type="dataset",
            provider="odin-live-signal",
            doc_id="d",
            title="t",
            content="c",
        )
        QueryRequest(query="q", grounding_evidence=[ok] * 7)


def test_grounding_evidence_roundtrips_through_codec():
    item = to_evidence_item(
        {
            "source_type": "dataset",
            "provider": "odin-country-almanac",
            "doc_id": "odin-country-almanac:rev:2026-05-17:DEU",
            "title": "Germany — ODIN country almanac",
            "content": "facts",
            "url": None,
            "score": 0.95,
        }
    )
    pack = format_evidence_pack([item], budget=2000)
    refs = parse_evidence_refs(pack)
    assert refs and refs[0].provider == "odin-country-almanac"
    assert refs[0].source_type == "dataset"


@pytest.mark.asyncio
async def test_grounding_reaches_react_seed_and_synthesis_sources(monkeypatch):
    from langchain_core.messages import AIMessage

    import graph.workflow as wf

    captured: dict = {}

    class FakeReact:
        async def ainvoke(self, messages):
            captured["messages"] = messages
            return AIMessage(content="done")  # no tool_calls → routes to synthesis

    monkeypatch.setattr(wf, "create_react_agent", lambda: FakeReact())
    seed_state = {
        "query": "Lage Iran",
        "image_url": None,
        "messages": [],
        "iteration": 0,
        "tool_calls_count": 0,
        "agent_chain": [],
        "tool_trace": [],
        "grounding_context": "<<<GROUNDING_DATA\nfakten\n>>>END_GROUNDING_DATA",
        "grounding_evidence_pack": "",
    }
    await wf.react_agent_node(seed_state)
    human = [m for m in captured["messages"] if getattr(m, "type", "") == "human"][0]
    assert "GROUNDING_DATA" in human.content  # grounding injected into ReAct seed

    synth_captured: dict = {}

    class FakeSynth:
        async def ainvoke(self, messages):
            synth_captured["messages"] = messages
            return AIMessage(content="HIGH — moderate confidence")

    monkeypatch.setattr(wf, "create_synthesis_llm", lambda: FakeSynth())
    pack = (
        '[EVIDENCE] {"provider":"odin-country-almanac","source_ref_id":"x","source_type":"dataset"}'
        "\nTitle: t\nExcerpt: e"
    )
    syn = await wf.react_synthesis_node(
        {
            "query": "Lage Iran",  # react_synthesis_node reads state["query"]
            "messages": [],
            "tool_trace": [],
            "agent_chain": [],
            "grounding_evidence_pack": pack,
        }
    )
    # grounding surfaces as a source
    assert "odin-country-almanac" in syn.get("sources_used", [])
    human = [m for m in synth_captured["messages"] if getattr(m, "type", "") == "human"][0]
    # evidence block embedded in the synthesis prompt
    assert "odin-country-almanac" in human.content
