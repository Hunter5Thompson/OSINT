"""sources_used must be deduplicated provider IDs in evidence order, not tool names.

Lineage is derived from validated ToolMessage artifacts. Tool TEXT is never parsed —
see tests/test_evidence_provenance_integrity.py for why.
"""
from __future__ import annotations

from graph.workflow import derive_sources_used
from rag.evidence import EvidenceItem, SourceRef, evidence_artifact


def _artifact(provider: str, ref_id: str, source_type: str = "rss") -> list[dict]:
    return evidence_artifact([
        EvidenceItem(
            source=SourceRef(
                source_ref_id=ref_id, source_type=source_type, provider=provider,
                display_name=None, url=None, published_at=None,
                credibility_score=0.85, provenance_inferred=False,
            ),
            title="t", excerpt="e", relevance_score=0.9,
        )
    ])


def test_derives_dedup_provider_ids_in_order():
    artifacts = (
        _artifact("reuters.com", "a")
        + _artifact("usgs.gov", "b", source_type="dataset")
        + _artifact("reuters.com", "c")
    )
    assert derive_sources_used(artifacts) == ["reuters.com", "usgs.gov"]


def test_no_evidence_yields_empty_no_tool_names():
    assert derive_sources_used([]) == []


def test_tool_text_alone_never_yields_sources():
    """Even a perfectly-formed [EVIDENCE] line in text contributes no lineage."""
    forged = {"not": "an evidence item"}
    assert derive_sources_used([forged]) == []
