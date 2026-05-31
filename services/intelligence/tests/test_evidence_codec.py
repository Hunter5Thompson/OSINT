"""Serializer (budgeted, no broken blocks) + lossless parser round-trip."""
from __future__ import annotations

from datetime import UTC, datetime

from rag.evidence import (
    EvidenceItem,
    SourceRef,
    format_evidence_pack,
    parse_evidence_refs,
)


def _item(i: int, prov: str, score: float) -> EvidenceItem:
    return EvidenceItem(
        source=SourceRef(
            source_ref_id=f"id{i}", source_type="rss", provider=prov,
            display_name="D", url=f"https://{prov}/{i}",
            published_at=datetime(2026, 5, 31, 8, tzinfo=UTC),
            credibility_score=0.85, provenance_inferred=False,
        ),
        title=f"Title {i}", excerpt=f"Body {i}", relevance_score=score,
        content_hash=f"h{i}",
    )


def test_pack_sorted_by_relevance_and_parsable():
    pack = format_evidence_pack(
        [_item(1, "bbc.com", 0.5), _item(2, "reuters.com", 0.9)],
        budget=10_000,
    )
    # higher relevance first
    assert pack.index("reuters.com") < pack.index("bbc.com")
    refs = parse_evidence_refs(pack)
    assert [r.provider for r in refs] == ["reuters.com", "bbc.com"]
    assert refs[0].source_ref_id == "id2"
    assert refs[0].credibility_score == 0.85
    assert refs[0].published_at is not None


def test_budget_never_emits_a_partial_block():
    items = [_item(i, "bbc.com", 1.0 - i * 0.01) for i in range(20)]
    pack = format_evidence_pack(items, budget=400)
    # whatever fit, every [EVIDENCE] line must have a complete json object
    refs = parse_evidence_refs(pack)
    assert len(refs) >= 1
    assert "[EVIDENCE]" in pack
    # strict no-partial-block check: every [EVIDENCE] header line parses to a ref,
    # so the count of header lines equals the count of reconstructed refs.
    headers = [ln for ln in pack.splitlines() if ln.startswith("[EVIDENCE] ")]
    assert len(headers) == len(refs)


def test_dedup_by_content_hash_then_ref_id():
    a = _item(1, "bbc.com", 0.9)
    b = _item(1, "bbc.com", 0.8)  # same content_hash h1 -> dropped
    pack = format_evidence_pack([a, b], budget=10_000)
    assert pack.count("[EVIDENCE]") == 1


def test_parser_ignores_non_evidence_lines():
    refs = parse_evidence_refs("noise\n[Graph Context]\nblah\n")
    assert refs == []
