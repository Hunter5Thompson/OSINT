"""Read-side evidence layer: models, normalization adapter, [EVIDENCE] codec.

This module is internal to the intelligence service. SourceRef objects are NEVER
serialized across the /query API boundary (Slice 1 keeps sources_used: list[str]).
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel

from rag.credibility import credibility_score, normalize_provider

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


EXCERPT_MAX_CHARS = 700

# Documentation guard (not runtime-enforced): event/observation timestamps that
# must NEVER be reinterpreted as published_at. Enforcement is structural — these
# keys simply have no code path into published_raw in _legacy_provenance.
_EVENT_TIME_KEYS = (
    "event_time", "event_date", "date_start", "from_date", "acq_date",
    "seendate", "gdelt_date",
)


def _excerpt(payload: dict) -> str:
    for key in ("content", "summary", "description", "title"):
        val = payload.get(key)
        if val:
            return str(val)[:EXCERPT_MAX_CHARS]
    return ""


def _parse_dt(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    # Naive timestamps in OSINT feeds mean UTC; make them explicit so downstream
    # comparisons (recency, Slice 2) never mix naive and aware datetimes.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _canonical_provenance(payload: dict) -> tuple[str, str, str | None, bool] | None:
    """Return (source_type, provider, published_at_raw, inferred=False) if the
    payload already carries canonical contract fields, else None."""
    st = payload.get("source_type")
    pv = payload.get("provider")
    if st and pv:
        return str(st), str(pv), payload.get("published_at"), False
    return None


def _legacy_provenance(payload: dict) -> tuple[str, str, str | None]:
    """Small explicit legacy matchers. Returns (source_type, provider, published_raw).
    Anything unmatched -> ('unknown', '?', None). Never guesses."""
    src = str(payload.get("source", "")).lower()
    if "notebook_id" in payload:
        nb = payload.get("notebook_id", "")
        return "notebooklm", f"notebooklm:{nb}", None
    if "telegram_channel" in payload or src == "telegram":
        handle = str(payload.get("telegram_channel", "")).lstrip("@").lower()
        return "telegram", f"telegram:{handle}" if handle else "telegram", payload.get("published")
    if src == "rss":
        # legacy rss: published carries publication time
        prov = str(payload.get("feed_name") or payload.get("provider") or "rss").lower()
        return "rss", prov, payload.get("published")
    if src in ("gdelt", "gdelt_gkg"):
        return "gdelt", str(payload.get("source_name") or "gdelt").lower(), None
    return "unknown", "?", None


def to_evidence_item(result: dict) -> "EvidenceItem":
    """Normalize one retriever result dict into an EvidenceItem.

    Order: canonical contract fields -> small explicit legacy matchers -> unknown.
    """
    canonical = _canonical_provenance(result)
    if canonical is not None:
        source_type, provider, published_raw, inferred = canonical
    else:
        source_type, provider, published_raw = _legacy_provenance(result)
        inferred = True

    # published_at is only ever the publication time. Never an event/observation time.
    published_at = _parse_dt(published_raw) if published_raw else None

    external_key = (
        result.get("doc_id")
        or (f"{result.get('telegram_channel')}:{result.get('telegram_message_id')}"
            if result.get("telegram_message_id") is not None else None)
        or (f"{result.get('notebook_id')}:{result.get('source_kind')}:{result.get('source_id')}"
            if result.get("notebook_id") else None)
        or result.get("ucdp_id")
    )
    title = str(result.get("title", "Untitled"))
    excerpt = _excerpt(result)
    content_hash = result.get("content_hash")
    url = result.get("url")

    source_ref_id = compute_source_ref_id(
        source_type=source_type, provider=provider,
        external_key=str(external_key) if external_key else None,
        url=url, content_hash=content_hash, title=title, excerpt=excerpt,
    )

    ref = SourceRef(
        source_ref_id=source_ref_id,
        source_type=source_type,
        provider=normalize_provider(provider),
        display_name=result.get("source_name") or result.get("feed_name"),
        url=url,
        published_at=published_at,
        credibility_score=credibility_score(source_type, provider),
        provenance_inferred=inferred,
    )
    return EvidenceItem(
        source=ref,
        title=title,
        excerpt=excerpt,
        relevance_score=float(result.get("score", 0.0)),
        content_hash=str(content_hash) if content_hash else None,
    )


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
