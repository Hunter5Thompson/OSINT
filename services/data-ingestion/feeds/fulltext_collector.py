"""Decoupled think-tank full-text enrichment collector.

Scrolls think-tank RSS teasers, fetches full text (crawl4ai/docling), chunks,
embeds, upserts rss_fulltext points (canonical provenance + inherited entities),
then soft-supersedes the teaser by record.id with a 4-state status model."""
from __future__ import annotations

import asyncio
import hashlib
import time
from datetime import UTC, datetime
from urllib.parse import urlparse, urlunparse

import httpx
import structlog
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct

from config import settings
from feeds._fulltext_fetch import fetch_fulltext
from feeds.fulltext_chunker import chunk_markdown
from qdrant_doctor.schema import validate_collection_schema

log = structlog.get_logger(__name__)

_TERMINAL = ("done", "failed_permanent", "skipped_paywall")

# feed_name -> canonical provider domain (verified against rss_collector.py feed config)
THINKTANK_FEEDS: dict[str, str] = {
    "CSIS": "csis.org",
    "RUSI Commentary": "rusi.org",
    "RUSI Publications": "rusi.org",
    "RAND Corporation": "rand.org",
    "SIPRI": "sipri.org",
    "SWP Publications (DE)": "swp-berlin.org",
    "SWP Publications (EN)": "swp-berlin.org",
    "Atlantic Council": "atlanticcouncil.org",
    "Brookings": "brookings.edu",
    "Crisis Group": "crisisgroup.org",
    "War on the Rocks": "warontherocks.com",
    "Bellingcat": "bellingcat.com",
}


def normalize_url(url: str) -> str:
    """Normalize for stable IDs: strip whitespace + trailing slash; lowercase
    scheme + host (the RFC 3986 case-insensitive parts), preserve path case."""
    cleaned = (url or "").strip().rstrip("/")
    parsed = urlparse(cleaned)
    return urlunparse(parsed._replace(scheme=parsed.scheme.lower(), netloc=parsed.netloc.lower()))


def article_id(url: str) -> str:
    return hashlib.sha256(normalize_url(url).encode()).hexdigest()[:16]


def _chunk_uid(url: str, chunk_index: int) -> str:
    return hashlib.sha256(f"rss_fulltext|{normalize_url(url)}|{chunk_index}".encode()).hexdigest()


def fulltext_point_id(url: str, chunk_index: int) -> int:
    """Deterministic uint64 (Qdrant accepts uint64/UUID, not raw hex) → re-run upserts."""
    return int(_chunk_uid(url, chunk_index)[:16], 16)


def build_fulltext_payload(
    teaser: dict,
    *,
    provider: str,
    chunk_text: str,
    chunk_index: int,
    chunk_count: int,
) -> dict:
    """Pure rss_fulltext payload (no I/O). Canonical provenance + inherited teaser meta."""
    url = teaser["url"]  # URL is required; KeyError here is the intended fail-fast
    return {
        "source": "rss_fulltext",
        "source_type": "rss",                 # canonical → credibility/tiering/guard
        "provider": provider,                 # feed domain → domain credibility override
        "feed_name": teaser.get("feed_name"),
        "url": normalize_url(url),
        "title": teaser.get("title"),
        "published_at": teaser.get("published_at"),
        "published": teaser.get("published"),  # legacy compat
        # defensive copy — INHERITED entities, no LLM re-extraction
        "entities": list(teaser.get("entities", [])),
        "content": chunk_text,
        "content_hash": hashlib.sha256(chunk_text.encode()).hexdigest()[:16],
        "chunk_uid": _chunk_uid(url, chunk_index),
        "fulltext_article_id": article_id(url),
        "chunk_index": chunk_index,
        "chunk_count": chunk_count,
        "ingested_at": datetime.now(UTC).isoformat(),
    }


class FulltextCollector:
    """Decoupled full-text enrichment: select teasers → fetch → chunk → embed →
    upsert chunks → soft-supersede teaser. Two-phase (NOT atomic): a crash between
    the chunk upsert and the supersede self-heals next run (deterministic IDs +
    re-select, because the teaser is not yet marked terminal)."""

    def __init__(self, qdrant: QdrantClient | None = None) -> None:
        self.qdrant = qdrant or QdrantClient(url=settings.qdrant_url)
        self._last_fetch: dict[str, float] = {}

    def _ensure_collection_ready(self) -> None:
        """Schema preflight before any write (matches the other collectors)."""
        names = [c.name for c in self.qdrant.get_collections().collections]
        if settings.qdrant_collection not in names:
            raise RuntimeError(f"collection {settings.qdrant_collection!r} missing")
        info = self.qdrant.get_collection(settings.qdrant_collection)
        validate_collection_schema(info, enable_hybrid=settings.enable_hybrid)

    async def _throttle(self, domain: str) -> None:
        wait = settings.fulltext_rate_limit_per_domain_s - (
            time.time() - self._last_fetch.get(domain, 0.0)
        )
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_fetch[domain] = time.time()

    async def _embed(self, text: str) -> list[float]:
        """Generate embedding vector via TEI (matches rss_collector._embed)."""
        async with httpx.AsyncClient(timeout=settings.http_timeout) as client:
            resp = await client.post(
                f"{settings.tei_embed_url}/embed",
                json={"inputs": text},
            )
            resp.raise_for_status()
            result = resp.json()
            # TEI returns [[...floats...]] for single input
            return result[0] if isinstance(result[0], list) else result

    def _select(self) -> list:
        """Scroll un-superseded, non-terminal think-tank teasers whose backoff has
        elapsed. Sync (called via asyncio.to_thread)."""
        from qdrant_client.models import (
            FieldCondition,
            Filter,
            MatchAny,
            MatchValue,
        )

        flt = Filter(
            must=[
                FieldCondition(key="source", match=MatchValue(value="rss")),
                FieldCondition(key="feed_name", match=MatchAny(any=list(THINKTANK_FEEDS))),
            ],
            must_not=[
                FieldCondition(key="superseded_by_fulltext", match=MatchValue(value=True)),
                FieldCondition(key="fulltext_status", match=MatchAny(any=list(_TERMINAL))),
            ],
        )
        points, _ = self.qdrant.scroll(
            collection_name=settings.qdrant_collection,
            scroll_filter=flt,
            limit=settings.fulltext_batch_size,
            with_payload=True,
        )
        now = time.time()
        return [p for p in points if (p.payload or {}).get("fulltext_retry_epoch", 0) <= now]

    async def collect(self) -> None:
        # Schema preflight before select/writes — propagates on mismatch (nothing upserted).
        await asyncio.to_thread(self._ensure_collection_ready)
        records = await asyncio.to_thread(self._select)
        log.info("fulltext_batch", count=len(records))
        for rec in records:
            try:
                await self._process(rec)
            except Exception as exc:
                # Resilience: a transient embed/upsert failure (TEI shares the GPU and
                # swaps out) must not abort the whole batch. Route to retry+backoff;
                # if even the mark fails, log and move on (self-heals next run).
                log.exception("fulltext_record_failed", record_id=getattr(rec, "id", None))
                try:
                    await self._mark_retry(rec, str(exc))
                except Exception:
                    log.exception("fulltext_mark_retry_failed",
                                  record_id=getattr(rec, "id", None))

    async def _process(self, rec) -> None:
        pl = rec.payload or {}
        url, feed = pl.get("url"), pl.get("feed_name")
        provider = THINKTANK_FEEDS.get(feed, "")
        await self._throttle(urlparse(url).hostname or provider)
        try:
            md = await fetch_fulltext(
                url,
                crawl4ai_url=settings.crawl4ai_url,
                docling_url=settings.docling_url,
                min_chars=settings.fulltext_min_body_chars,
                min_paras=settings.fulltext_min_paragraphs,
            )
        except httpx.HTTPError as exc:
            return await self._mark_retry(rec, str(exc))
        if md is None:
            return await self._mark(rec, {
                "fulltext_status": "skipped_paywall",
                "fulltext_attempted_at": _now(),
            })
        chunks = chunk_markdown(
            md,
            target_tokens=settings.fulltext_chunk_tokens,
            overlap_tokens=settings.fulltext_chunk_overlap,
        )
        points = []
        for i, ch in enumerate(chunks):
            vec = await self._embed(ch)
            points.append(PointStruct(
                id=fulltext_point_id(url, i),
                vector=vec,
                payload=build_fulltext_payload(
                    pl,
                    provider=provider,
                    chunk_text=ch,
                    chunk_index=i,
                    chunk_count=len(chunks),
                ),
            ))
        # Phase 1: upsert chunks. Phase 2: supersede the teaser. NEVER reorder these.
        await asyncio.to_thread(
            self.qdrant.upsert,
            collection_name=settings.qdrant_collection,
            points=points,
        )
        await self._mark(rec, {
            "superseded_by_fulltext": True,
            "fulltext_status": "done",
            "fulltext_article_id": article_id(url),
            "fulltext_chunk_count": len(chunks),
            "fulltext_ingested_at": _now(),
        })

    async def _mark(self, rec, payload: dict) -> None:
        """Soft-update the teaser by its Qdrant record.id (NOT url)."""
        await asyncio.to_thread(
            self.qdrant.set_payload,
            collection_name=settings.qdrant_collection,
            payload=payload,
            points=[rec.id],
            wait=True,
        )

    async def _mark_retry(self, rec, error: str) -> None:
        attempts = int((rec.payload or {}).get("fulltext_attempts", 0)) + 1
        status = "failed_permanent" if attempts >= settings.fulltext_max_attempts else "retry"
        backoff = min(3600, 60 * (2 ** attempts))
        await self._mark(rec, {
            "fulltext_status": status,
            "fulltext_attempts": attempts,
            "fulltext_attempted_at": _now(),
            "fulltext_error": error[:300],
            "fulltext_retry_epoch": time.time() + backoff,
        })

    async def close(self) -> None:
        await asyncio.to_thread(self.qdrant.close)


def _now() -> str:
    return datetime.now(UTC).isoformat()
