"""SourceRef / EvidenceItem model contract."""
from __future__ import annotations

from datetime import UTC, datetime

from rag.evidence import EvidenceItem, SourceRef


def test_sourceref_defaults():
    ref = SourceRef(
        source_ref_id="abc123",
        source_type="rss",
        provider="reuters.com",
    )
    assert ref.display_name is None
    assert ref.url is None
    assert ref.published_at is None
    assert ref.credibility_score == 0.5  # filled later by the adapter
    assert ref.provenance_inferred is False


def test_sourceref_accepts_unknown_read_only_type():
    ref = SourceRef(source_ref_id="x", source_type="unknown", provider="?")
    assert ref.source_type == "unknown"


def test_evidence_item_holds_source_and_text():
    ref = SourceRef(source_ref_id="x", source_type="rss", provider="bbc.com")
    item = EvidenceItem(
        source=ref,
        title="Headline",
        excerpt="body text",
        relevance_score=0.82,
        content_hash="deadbeef",
    )
    assert item.source.provider == "bbc.com"
    assert item.content_hash == "deadbeef"
    # published_at round-trips as datetime
    ref2 = SourceRef(
        source_ref_id="y", source_type="rss", provider="bbc.com",
        published_at=datetime(2026, 5, 31, 8, 0, tzinfo=UTC),
    )
    assert ref2.published_at.year == 2026
