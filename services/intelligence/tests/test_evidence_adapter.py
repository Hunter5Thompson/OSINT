"""Adapter: retriever dict -> EvidenceItem. Canonical first, then legacy, then unknown."""
from __future__ import annotations

from rag.evidence import to_evidence_item


def test_canonical_payload_is_read_directly():
    item = to_evidence_item({
        "score": 0.9,
        "source_type": "rss",
        "provider": "reuters.com",
        "title": "Tanker seized",
        "content": "full body",
        "url": "https://reuters.com/a",
        "published_at": "2026-05-31T08:00:00+00:00",
        "content_hash": "h1",
    })
    assert item.source.source_type == "rss"
    assert item.source.provider == "reuters.com"
    assert item.source.provenance_inferred is False
    assert item.source.credibility_score == 0.85  # override
    assert item.excerpt == "full body"
    assert item.source.published_at is not None


def test_legacy_nlm_shape_is_inferred():
    item = to_evidence_item({
        "score": 0.7,
        "source": "unknown",
        "notebook_id": "nb-7",
        "source_kind": "report",
        "source_id": "rpt-3",
        "title": "Notebook claim",
        "content": "claim text",
    })
    assert item.source.source_type == "notebooklm"
    assert item.source.provenance_inferred is True
    assert item.source.provider.startswith("notebooklm:")


def test_legacy_rss_shape_is_inferred():
    item = to_evidence_item({
        "score": 0.6, "source": "rss", "feed_name": "BBC World",
        "title": "x", "summary": "sum", "url": "https://bbc.com/x",
        "published": "2026-05-30T00:00:00+00:00",
    })
    assert item.source.source_type == "rss"
    assert item.source.provenance_inferred is True


def test_unmatched_shape_is_unknown_not_guessed():
    item = to_evidence_item({"score": 0.4, "title": "mystery", "content": "?"})
    assert item.source.source_type == "unknown"
    assert item.source.provenance_inferred is True
    assert item.source.credibility_score == 0.30


def test_excerpt_priority_and_700_cap():
    item = to_evidence_item({
        "score": 0.5, "source_type": "dataset", "provider": "usgs.gov",
        "summary": "s" * 1000, "title": "t",
    })
    assert item.excerpt == "s" * 700  # content missing -> summary, capped at 700


def test_event_time_is_not_published_at():
    item = to_evidence_item({
        "score": 0.5, "source_type": "dataset", "provider": "usgs.gov",
        "title": "quake", "content": "m6", "event_time": "2026-05-31T00:00:00+00:00",
    })
    assert item.source.published_at is None  # event_time != published_at
