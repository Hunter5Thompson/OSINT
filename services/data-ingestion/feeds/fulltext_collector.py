"""Decoupled think-tank full-text enrichment collector.

Scrolls think-tank RSS teasers, fetches full text (crawl4ai/docling), chunks,
embeds, upserts rss_fulltext points (canonical provenance + inherited entities),
then soft-supersedes the teaser by record.id with a 4-state status model."""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from urllib.parse import urlparse, urlunparse

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
