# services/intelligence/tests/test_grounding.py
import pytest
from pydantic import ValidationError

from main import GroundingEvidenceItem, QueryRequest
from rag.evidence import format_evidence_pack, to_evidence_item
from tests._evidence_text import parse_evidence_refs

TOKEN_JSON = {
    "schema_version": 1,
    "scope_key": "country:UKR",
    "kind": "country",
    "catalog_revision": "spatial-v1-e76a16bff799",
    "derivation_revision": "spatial-derive-v1-d30efa07e141",
    "boundary_policy": "odin-reference-v1",
    "compatible_derivation_revisions": ["spatial-derive-v1-d30efa07e141"],
}


def test_query_request_bounds_and_allowlist():
    QueryRequest(
        query="q",
        spatial_relation="either",
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
        QueryRequest(query="q", spatial_relation="either", grounding_context="x" * 4001)
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
        QueryRequest(query="q", spatial_relation="either", grounding_evidence=[ok] * 7)


def test_internal_query_requires_relation_and_validates_frozen_token() -> None:
    with pytest.raises(ValidationError):
        QueryRequest(query="q")

    request = QueryRequest(
        query="q",
        spatial_scope=TOKEN_JSON,
        spatial_relation="occurrence",
    )

    assert request.spatial_scope is not None
    assert request.spatial_scope.scope_key == "country:UKR"
    assert request.spatial_relation.value == "occurrence"

    with pytest.raises(ValidationError):
        QueryRequest(
            query="q",
            spatial_scope={**TOKEN_JSON, "unexpected": True},
            spatial_relation="either",
        )


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
async def test_grounding_pack_and_artifact_share_budget_and_order(monkeypatch):
    """Only grounding blocks that fit the prompt budget may carry lineage."""
    import graph.workflow as wf
    from rag.evidence import source_refs_from_artifact

    captured: dict = {}

    class FakeGraph:
        async def ainvoke(self, state):
            captured["state"] = state
            return {
                "synthesis": "ok",
                "sources_used": [],
                "agent_chain": [],
                "tool_trace": [],
            }

    monkeypatch.setattr(wf, "_ensure_graph_client", lambda: None)
    monkeypatch.setattr(wf, "react_graph", FakeGraph())
    scores = (0.1, 0.6, 0.2, 0.5, 0.3, 0.4)
    grounding = [
        {
            "source_type": "dataset",
            "provider": "odin-country-almanac",
            "doc_id": f"grounding-{index}",
            "title": f"Grounding {index}",
            "content": "x" * 700,
            "score": score,
        }
        for index, score in enumerate(scores)
    ]

    await wf.run_intelligence_query("budget parity", grounding_evidence=grounding)

    state = captured["state"]
    rendered_ids = [
        ref.source_ref_id
        for ref in parse_evidence_refs(state["grounding_evidence_pack"])
    ]
    artifact_ids = [
        ref.source_ref_id
        for ref in source_refs_from_artifact(state["grounding_evidence_artifact"])
    ]
    assert 0 < len(rendered_ids) < len(grounding)
    assert artifact_ids == rendered_ids


@pytest.mark.asyncio
async def test_grounding_reaches_react_seed_and_synthesis_sources(monkeypatch):
    from langchain_core.messages import AIMessage

    import graph.workflow as wf

    captured: dict = {}

    class FakeReact:
        async def ainvoke(self, messages):
            captured["messages"] = messages
            return AIMessage(content="done")  # no tool_calls → routes to synthesis

    monkeypatch.setattr(wf, "create_react_agent", lambda _tools: FakeReact())
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
    from rag.evidence import EvidenceItem, SourceRef, evidence_artifact, format_evidence_pack

    grounding_item = EvidenceItem(
        source=SourceRef(
            source_ref_id="x", source_type="dataset", provider="odin-country-almanac",
            display_name=None, url=None, published_at=None,
            credibility_score=0.8, provenance_inferred=False,
        ),
        title="t", excerpt="e", relevance_score=1.0,
    )
    pack = format_evidence_pack([grounding_item], budget=5000)
    syn = await wf.react_synthesis_node(
        {
            "query": "Lage Iran",  # react_synthesis_node reads state["query"]
            "messages": [],
            "tool_trace": [],
            "agent_chain": [],
            "grounding_evidence_pack": pack,
            # Provenance travels structurally — the pack is prompt text only.
            "grounding_evidence_artifact": evidence_artifact([grounding_item]),
        }
    )
    # grounding surfaces as a source
    assert "odin-country-almanac" in syn.get("sources_used", [])
    human = [m for m in synth_captured["messages"] if getattr(m, "type", "") == "human"][0]
    # evidence block embedded in the synthesis prompt
    assert "odin-country-almanac" in human.content
