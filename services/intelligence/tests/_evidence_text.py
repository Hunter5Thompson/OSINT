"""Test-only helper: reconstruct SourceRefs from rendered pack TEXT.

Deliberately NOT in rag.evidence — parsing provenance out of text is exactly the
forgery vector closed on 2026-08-21 (untrusted excerpts, graph context and echoed
tool arguments all land in that same text). Production lineage comes from
`ToolMessage.artifact` via `graph.workflow.collect_evidence_artifacts`.

This helper exists only so tests can assert on what a pack RENDERS.
"""
from __future__ import annotations

import json

from rag.evidence import _EVIDENCE_PREFIX, SourceRef, _parse_dt


def parse_evidence_refs(text: str) -> list[SourceRef]:
    """Reconstruct SourceRef from every complete [EVIDENCE] <json> line.
    Lines that don't parse are ignored. Order preserved."""
    refs: list[SourceRef] = []
    for line in text.splitlines():
        if not line.startswith(_EVIDENCE_PREFIX):
            continue
        try:
            meta = json.loads(line[len(_EVIDENCE_PREFIX):])
        except (ValueError, json.JSONDecodeError):
            continue
        try:
            refs.append(SourceRef(
                source_ref_id=meta["source_ref_id"],
                source_type=meta["source_type"],
                provider=meta["provider"],
                display_name=meta.get("display_name"),
                url=meta.get("url"),
                published_at=_parse_dt(meta.get("published_at")),
                credibility_score=meta.get("credibility_score", 0.5),
                provenance_inferred=meta.get("provenance_inferred", False),
            ))
        except (KeyError, ValueError, TypeError):
            continue
    return refs
