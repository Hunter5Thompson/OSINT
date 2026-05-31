"""Read-side evidence layer: models, normalization adapter, [EVIDENCE] codec.

This module is internal to the intelligence service. SourceRef objects are NEVER
serialized across the /query API boundary (Slice 1 keeps sources_used: list[str]).
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

SourceType = Literal["rss", "telegram", "gdelt", "notebooklm", "dataset", "unknown"]


class SourceRef(BaseModel):
    source_ref_id: str
    source_type: SourceType
    provider: str                       # canonical id
    display_name: str | None = None     # not scoring-relevant
    url: str | None = None
    published_at: datetime | None = None
    credibility_score: float = 0.5      # filled read-side from the registry
    provenance_inferred: bool = False


class EvidenceItem(BaseModel):
    source: SourceRef
    title: str
    excerpt: str
    relevance_score: float
    content_hash: str | None = None     # for dedup only, not public provenance
