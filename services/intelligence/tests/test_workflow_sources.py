"""sources_used must be deduplicated provider IDs in evidence order, not tool names."""
from __future__ import annotations

from graph.workflow import derive_sources_used


def test_derives_dedup_provider_ids_in_order():
    tool_outputs = [
        '[Knowledge Base Evidence for: x]\n'
        '[EVIDENCE] {"provider":"reuters.com","source_ref_id":"a","source_type":"rss",'
        '"credibility_score":0.85,"provenance_inferred":false,"published_at":null,'
        '"relevance_score":0.9,"url":null,"display_name":null}\nTitle: t\nExcerpt: e',
        '[GDELT Evidence for: x]\n'
        '[EVIDENCE] {"provider":"usgs.gov","source_ref_id":"b","source_type":"dataset",'
        '"credibility_score":0.8,"provenance_inferred":false,"published_at":null,'
        '"relevance_score":0.7,"url":null,"display_name":null}\nTitle: t2\nExcerpt: e2',
        '[EVIDENCE] {"provider":"reuters.com","source_ref_id":"c","source_type":"rss",'
        '"credibility_score":0.85,"provenance_inferred":false,"published_at":null,'
        '"relevance_score":0.6,"url":null,"display_name":null}\nTitle: t3\nExcerpt: e3',
    ]
    assert derive_sources_used(tool_outputs) == ["reuters.com", "usgs.gov"]


def test_no_evidence_yields_empty_no_tool_names():
    assert derive_sources_used(["No relevant documents found for: x"]) == []


def test_empty_tool_outputs_yields_empty():
    assert derive_sources_used([]) == []
