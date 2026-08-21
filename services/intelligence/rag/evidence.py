"""Read-side evidence layer: models, normalization adapter, [EVIDENCE] codec.

This module is internal to the intelligence service. SourceRef objects are NEVER
serialized across the /query API boundary (Slice 1 keeps sources_used: list[str]).

TRUST SEAM: provenance is carried by the structured artifact (`evidence_artifact`),
never by the rendered text. The [EVIDENCE] codec is prompt formatting for the LLM —
it is NOT an authentication mechanism, because untrusted text (excerpts, graph
context, echoed tool arguments) reaches the same output stream.
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ValidationError

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
    source_class: str | None = None     # "realtime" marks an unverified lead


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
        dt = dt.replace(tzinfo=UTC)
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


def to_evidence_item(result: dict) -> EvidenceItem:
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
        display_name=(
            result.get("display_name") or result.get("source_name") or result.get("feed_name")
        ),
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
        source_class=result.get("source_class"),
    )


_EVIDENCE_PREFIX = "[EVIDENCE] "


def _block(item: EvidenceItem) -> str:
    s = item.source
    meta = {
        "credibility_score": s.credibility_score,
        "display_name": s.display_name,
        "provenance_inferred": s.provenance_inferred,
        "provider": s.provider,
        "published_at": s.published_at.isoformat() if s.published_at else None,
        "relevance_score": item.relevance_score,
        "source_ref_id": s.source_ref_id,
        "source_type": s.source_type,
        "url": s.url,
    }
    if item.source_class:
        meta["source_class"] = item.source_class
    header = _EVIDENCE_PREFIX + json.dumps(meta, sort_keys=True, separators=(",", ":"))
    return f"{header}\nTitle: {item.title}\nExcerpt: {item.excerpt}"


def select_pack_items(items: list[EvidenceItem], *, budget: int,
                      preserve_order: bool = False) -> list[EvidenceItem]:
    """The items a pack of this budget actually keeps — deduped, whole blocks only.

    Split out from rendering so lineage can be derived from the SAME selection:
    an artifact must never claim a source whose block was dropped for budget.
    """
    ordered = items if preserve_order else sorted(
        items, key=lambda it: it.relevance_score, reverse=True)
    seen: set[str] = set()
    kept: list[EvidenceItem] = []
    used = 0
    for it in ordered:
        key = it.content_hash or it.source.source_ref_id
        if key in seen:
            continue
        block = _block(it)
        add = len(block) + (2 if kept else 0)  # "\n\n" separator
        if used + add > budget:
            continue  # try the next (smaller) block; never truncate
        seen.add(key)
        kept.append(it)
        used += add
    return kept


def format_evidence_pack(items: list[EvidenceItem], *, budget: int,
                         preserve_order: bool = False) -> str:
    """Deterministic, budgeted pack. Deduped, and a block is only appended if it
    fits whole — never a partial/truncated block.

    If preserve_order, items are emitted in the caller's order (already ranked);
    otherwise sorted by relevance desc.
    """
    return "\n\n".join(
        _block(it) for it in select_pack_items(
            items, budget=budget, preserve_order=preserve_order))


def pack_with_lineage(items: list[EvidenceItem], *, budget: int,
                      preserve_order: bool = False) -> tuple[str, list[dict]]:
    """Rendered pack plus the matching provenance artifact — the pair tools return."""
    kept = select_pack_items(items, budget=budget, preserve_order=preserve_order)
    return "\n\n".join(_block(it) for it in kept), evidence_artifact(kept)


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


# --- Structured provenance artifact (the trust seam) --------------------------


def evidence_artifact(items: list[EvidenceItem]) -> list[dict]:
    """Serialize evidence for `ToolMessage.artifact` — the only lineage carrier.

    Kept as EvidenceItem payloads (not bare SourceRefs) so the corroboration slice
    can consume excerpts structurally without another transport change.
    """
    return [item.model_dump(mode="json") for item in items]


def evidence_items_from_artifact(artifact: object) -> list[EvidenceItem]:
    """Validate an artifact into EvidenceItems, dropping malformed entries."""
    if not isinstance(artifact, list):
        return []
    items: list[EvidenceItem] = []
    for entry in artifact:
        if not isinstance(entry, dict):
            continue
        try:
            items.append(EvidenceItem.model_validate(entry))
        except ValidationError:
            continue
    return items


def source_refs_from_artifact(artifact: object) -> list[SourceRef]:
    """Validate an artifact into SourceRefs. Fail-closed: anything that is not a
    well-formed EvidenceItem payload is dropped, never guessed at."""
    return [item.source for item in evidence_items_from_artifact(artifact)]


def neutralize_evidence_markers(text: str) -> str:
    """Defense-in-depth for the prompt surface: keep untrusted text from imitating
    a codec header line. Carries no security guarantee on its own — provenance
    integrity lives in the artifact — but stops the LLM from reading forged
    metadata as if the system had emitted it."""
    if not text or _EVIDENCE_PREFIX not in text:
        return text
    return "\n".join(
        ("\u2007" + line if line.startswith(_EVIDENCE_PREFIX) else line)
        for line in text.split("\n")
    )
