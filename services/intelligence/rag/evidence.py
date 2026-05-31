"""Read-side evidence layer: models, normalization adapter, [EVIDENCE] codec.

This module is internal to the intelligence service. SourceRef objects are NEVER
serialized across the /query API boundary (Slice 1 keeps sources_used: list[str]).
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from rag.credibility import normalize_provider

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


def compute_source_ref_id(
    *,
    source_type: str,
    provider: str,
    external_key: str | None,
    url: str | None,
    content_hash: str | None,
    title: str,
    excerpt: str,
) -> str:
    """Deterministic 20-char id. Identity = first non-empty of:
    external_key -> url -> content_hash -> normalized(title + excerpt)."""
    if external_key:
        kind, value = "ext", external_key
    elif url:
        kind, value = "url", url.strip()
    elif content_hash:
        kind, value = "hash", content_hash
    else:
        kind = "text"
        value = " ".join((title or "").split()) + "\x1f" + " ".join((excerpt or "").split())
    raw = "\x00".join(
        ["source-ref-v1", source_type, normalize_provider(provider), kind, value]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
