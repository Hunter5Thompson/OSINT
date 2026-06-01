from __future__ import annotations

from gdelt_raw.writers.qdrant_writer import build_payload


def test_gdelt_payload_provenance_uses_origin_domain():
    p = build_payload({
        "doc_id": "d1", "url": "https://reuters.com/x",
        "source_name": "reuters.com", "published_at": "2026-05-31T00:00:00+00:00",
    })
    assert p["source_type"] == "gdelt"
    assert p["provider"] == "reuters.com"


def test_gdelt_payload_provenance_falls_back_to_gdelt():
    p = build_payload({"doc_id": "d2", "url": None, "source_name": None})
    assert p["source_type"] == "gdelt"
    assert p["provider"] == "gdelt"


def test_gdelt_published_at_passthrough_not_seendate():
    # gdelt_date (observation) must NOT become published_at
    p = build_payload({"doc_id": "d3", "gdelt_date": "20260531120000", "published_at": None})
    assert p.get("published_at") is None
