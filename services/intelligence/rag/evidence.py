"""Read-side evidence layer: models, normalization adapter, [EVIDENCE] codec.

The public summary preserves reviewed claim provenance and citation IDs. Legacy
evidence retains its minimal time projection. Artifact metadata describes source
lineage, not independent factual validation.

TRUST SEAM: provenance is carried by the structured artifact (`evidence_artifact`),
never by the rendered text. The [EVIDENCE] codec is prompt formatting for the LLM —
it is NOT an authentication mechanism, because untrusted text (excerpts, graph
context, echoed tool arguments) reaches the same output stream.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from typing import Literal

from pydantic import AliasChoices, BaseModel, Field, ValidationError

from rag.credibility import credibility_score, normalize_provider
from rag.excerpts import select_excerpt

SourceType = Literal["rss", "web", "telegram", "gdelt", "notebooklm", "dataset", "unknown"]


class SourceRef(BaseModel):
    source_ref_id: str
    source_type: SourceType
    provider: str  # canonical id
    display_name: str | None = None  # not scoring-relevant
    url: str | None = None
    published_at: datetime | None = None
    credibility_score: float = 0.5  # filled read-side from the registry
    provenance_inferred: bool = False


class OriginalEvidence(BaseModel):
    """Original investigation, distinct from its Notebook storage location.

    The publication/reference value is verbatim; it is not an ISO timestamp.
    No day or date role is inferred from an ambiguous source label.
    """

    id: str
    title: str | None = None
    url: str | None = None
    sha256: str | None = None
    text_sha256: str | None = None
    publication_or_reference_date: str | None = None
    date_precision: Literal["as_recorded"] = "as_recorded"
    retrieved_at: str | None = None
    independent_lineage: str | None = None
    analyst_scope: str | None = None
    content_review: str | None = None


class SourceAnchor(BaseModel):
    sha256: str | None = None
    content_sha256: str | None = None
    anchor: str | None = None
    character_offset: int | None = None


class ReviewProvenance(BaseModel):
    candidate_id: str
    claim_id: str
    notebook_id: str
    original_source_id: str
    epistemic_type: str
    qualification_note: str = Field(
        validation_alias=AliasChoices("qualification_note", "qualification")
    )
    knowledge_domain: str | None = Field(default=None, exclude_if=lambda value: value is None)
    external_fact_verification: str | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    unresolved_checks: list[str] = Field(default_factory=list, exclude_if=lambda value: not value)
    source_date_context: str | None = None
    reviewed_at: str | None = None
    source_anchor: SourceAnchor | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    evidence_urls: list[str] = Field(default_factory=list)
    evidence: list[OriginalEvidence] = Field(default_factory=list)
    package_sha256: str
    factual_verification: str


class NotebookPassage(BaseModel):
    """A literal archive excerpt; an editorial review does not verify its claims."""

    notebook_id: str
    original_source_id: str
    source_sha256: str
    text_sha256: str
    start: int
    end: int
    passage_sha256: str
    independent_lineage: str
    package_sha256: str
    parent_candidate_id: str
    qualification_note: str
    unresolved_checks: list[str] = Field(default_factory=list)
    source_date_context: str | None = None
    content_review: Literal["unreviewed_source_excerpt"] = "unreviewed_source_excerpt"
    external_fact_verification: Literal["not_performed"] = "not_performed"


class RetrievalProvenance(BaseModel):
    """How a public document was read; retrieval does not verify its contents."""

    retrieved_at: datetime
    content_kind: Literal["snippet", "fulltext", "fulltext_chunk"]
    content_sha256: str
    publication_check: Literal[
        "not_checked", "not_found", "matched_day", "timezone_unresolved", "conflict"
    ] = "not_checked"
    original_publication_date: date | None = None
    source_chars: int = 0
    excerpt_truncated: bool = False
    original_lineage: str
    lineage_basis: Literal["url", "attribution", "identical_content"] = "url"
    temporal_basis: Literal["provider_publication", "source_publication", "unknown"] = "unknown"
    spatial_basis: Literal["topic_only", "scoped"] = "topic_only"


class EvidenceItem(BaseModel):
    evidence_id: str | None = None
    review: ReviewProvenance | None = None
    passage: NotebookPassage | None = None
    knowledge_role: Literal["source", "background", "method"] = "source"
    source: SourceRef
    title: str
    excerpt: str
    relevance_score: float
    content_hash: str | None = None  # for dedup only, not public provenance
    source_class: str | None = None  # "realtime" marks an unverified lead
    observed_at: datetime | None = None
    ingested_at: datetime | None = None
    retrieval: RetrievalProvenance | None = None
    # Read-side lineage is not an independent factual verification certificate.
    verification_status: Literal["unverified"] = "unverified"


EXCERPT_MAX_CHARS = 700

# Documentation guard (not runtime-enforced): event/observation timestamps that
# must NEVER be reinterpreted as published_at. Enforcement is structural — these
# keys simply have no code path into published_raw in _legacy_provenance.
_EVENT_TIME_KEYS = (
    "event_time",
    "event_date",
    "date_start",
    "from_date",
    "acq_date",
    "seendate",
    "gdelt_date",
)


def _excerpt(payload: dict) -> str:
    for key in ("content", "summary", "description", "title"):
        val = payload.get(key)
        if val:
            return str(val)[:EXCERPT_MAX_CHARS]
    return ""


def _parse_dt(value):
    if not isinstance(value, (str, datetime)) or not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        # Naive feed timestamps use UTC, without substituting a different time axis.
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except (ValueError, TypeError, OverflowError):
        return None


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
        # The independent legacy indexer writes this explicit publication field;
        # old collectors used published. Neither may fall back to ingestion time.
        published = payload.get("published_at")
        return "rss", prov, published if published is not None else payload.get("published")
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
        or (
            f"{result.get('telegram_channel')}:{result.get('telegram_message_id')}"
            if result.get("telegram_message_id") is not None
            else None
        )
        or (
            f"{result.get('notebook_id')}:{result.get('source_kind')}:{result.get('source_id')}"
            if result.get("notebook_id")
            else None
        )
        or result.get("ucdp_id")
    )
    review = ReviewProvenance.model_validate(result["review"]) if result.get("review") else None
    title = str(result.get("title", "Untitled"))
    excerpt = str(result.get("content", "")) if review else _excerpt(result)
    if result.get("source") == "rss_fulltext" or provider == "odin-live-signal":
        excerpt = select_excerpt(str(result.get("content", "")), title)
    content_hash = result.get("content_hash")
    url = result.get("url")

    source_ref_id = compute_source_ref_id(
        source_type=source_type,
        provider=provider,
        external_key=str(external_key) if external_key else None,
        url=url,
        content_hash=content_hash,
        title=title,
        excerpt=excerpt,
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
    claim_key = (
        f"{review.package_sha256}:{review.candidate_id}"
        if review
        else f"{source_ref_id}:{content_hash or excerpt}"
    )
    evidence_id = "ev-" + hashlib.sha256(claim_key.encode()).hexdigest()[:24]
    return EvidenceItem(
        evidence_id=evidence_id,
        review=review,
        knowledge_role=(
            "method"
            if review and review.knowledge_domain == "methods"
            else "background"
            if review and review.epistemic_type == "source_context"
            else "source"
        ),
        source=ref,
        title=title,
        excerpt=excerpt,
        relevance_score=float(result.get("score", 0.0)),
        content_hash=str(content_hash) if content_hash else None,
        retrieval=RetrievalProvenance(
            retrieved_at=datetime.now(UTC),
            content_kind="fulltext_chunk",
            content_sha256=hashlib.sha256(str(result.get("content", "")).encode()).hexdigest(),
            source_chars=len(str(result.get("content", ""))),
            excerpt_truncated=len(str(result.get("content", ""))) > len(excerpt),
            original_lineage=url or source_ref_id,
            temporal_basis="source_publication",
        )
        if result.get("source") == "rss_fulltext"
        else None,
        source_class=result.get("source_class"),
        observed_at=_parse_dt(result.get("observed_at")),
        ingested_at=_parse_dt(result.get("ingested_at")),
    )


def eligible_current_evidence(item: EvidenceItem, since: datetime, as_of: datetime) -> bool:
    """A source-availability gate, never an assertion of truth or event date."""
    if item.knowledge_role != "source" or not item.excerpt.strip():
        return False
    if item.source.provider == "odin-live-signal" and item.source.source_type == "dataset":
        return item.observed_at is not None and since <= item.observed_at <= as_of
    return (
        item.retrieval is not None
        and item.retrieval.content_kind in ("fulltext", "fulltext_chunk")
        and item.retrieval.publication_check != "conflict"
        and item.source.published_at is not None
        and since <= item.source.published_at <= as_of
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
        "verification_status": item.verification_status,
    }
    if item.evidence_id:
        meta["evidence_id"] = item.evidence_id
    if item.retrieval:
        meta["retrieval"] = item.retrieval.model_dump(mode="json")
    if item.review:
        meta["review"] = item.review.model_dump(mode="json")
    if item.passage:
        meta["passage"] = item.passage.model_dump(mode="json")
    if item.knowledge_role != "source":
        meta["knowledge_role"] = item.knowledge_role
    if item.observed_at is not None:
        meta["observed_at"] = item.observed_at.isoformat()
    if item.ingested_at is not None:
        meta["ingested_at"] = item.ingested_at.isoformat()
    if item.source_class:
        meta["source_class"] = item.source_class
    header = _EVIDENCE_PREFIX + json.dumps(meta, sort_keys=True, separators=(",", ":"))
    title = neutralize_evidence_markers(item.title)
    excerpt = neutralize_evidence_markers(item.excerpt)
    return f"{header}\nTitle: {title}\nExcerpt: {excerpt}"


def select_pack_items(
    items: list[EvidenceItem], *, budget: int, preserve_order: bool = False
) -> list[EvidenceItem]:
    """The items a pack of this budget actually keeps — deduped, whole blocks only.

    Split out from rendering so lineage can be derived from the SAME selection:
    an artifact must never claim a source whose block was dropped for budget.
    """
    ordered = (
        items if preserve_order else sorted(items, key=lambda it: it.relevance_score, reverse=True)
    )
    seen: set[str] = set()
    kept: list[EvidenceItem] = []
    used = 0
    for it in ordered:
        key = it.evidence_id or it.content_hash or it.source.source_ref_id
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


def format_evidence_pack(
    items: list[EvidenceItem], *, budget: int, preserve_order: bool = False
) -> str:
    """Deterministic, budgeted pack. Deduped, and a block is only appended if it
    fits whole — never a partial/truncated block.

    If preserve_order, items are emitted in the caller's order (already ranked);
    otherwise sorted by relevance desc.
    """
    return "\n\n".join(
        _block(it) for it in select_pack_items(items, budget=budget, preserve_order=preserve_order)
    )


def pack_with_lineage(
    items: list[EvidenceItem], *, budget: int, preserve_order: bool = False
) -> tuple[str, list[dict]]:
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
    raw = "\x00".join(["source-ref-v1", source_type, normalize_provider(provider), kind, value])
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


def evidence_time_summary(artifact: object) -> list[dict]:
    """Public time metadata for the consumed structural lineage, never parsed text."""
    seen: set[str] = set()
    result: list[dict] = []
    for item in evidence_items_from_artifact(artifact):

        def utc_value(value: datetime | None) -> str | None:
            parsed = _parse_dt(value)
            return parsed.isoformat() if parsed is not None else None

        row = {
            "source_ref_id": item.source.source_ref_id,
            "provider": item.source.provider,
            "source_type": item.source.source_type,
            "published_at": utc_value(item.source.published_at),
            "observed_at": utc_value(item.observed_at),
            "ingested_at": utc_value(item.ingested_at),
            "verification_status": "unverified",
        }
        if item.evidence_id:
            row["evidence_id"] = item.evidence_id
            # Generic dataset grounding retains its existing minimal projection.
            if (
                item.source.source_type in ("rss", "web")
                or item.source.provider == "odin-live-signal"
            ):
                row.update(title=item.title, excerpt=item.excerpt)
                if item.source.url:
                    row["url"] = item.source.url
        if item.retrieval:
            row["retrieval"] = item.retrieval.model_dump(mode="json")
        if item.review:
            row.update(
                evidence_id=item.evidence_id,
                title=item.title,
                excerpt=item.excerpt,
                review=item.review.model_dump(mode="json"),
            )
        if item.passage:
            row.update(
                evidence_id=item.evidence_id,
                title=item.title,
                excerpt=item.excerpt,
                url=item.source.url,
                knowledge_role=item.knowledge_role,
                passage=item.passage.model_dump(mode="json"),
            )
        if item.knowledge_role != "source":
            row["knowledge_role"] = item.knowledge_role
        key = json.dumps(row, sort_keys=True)
        if key not in seen:
            seen.add(key)
            result.append(row)
    return result


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
