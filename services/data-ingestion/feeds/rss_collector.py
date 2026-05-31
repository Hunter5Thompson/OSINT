"""RSS Feed Collector — fetches OSINT/intelligence RSS feeds, embeds, and upserts to Qdrant."""

from __future__ import annotations

import hashlib
import time
from datetime import UTC, datetime

import feedparser
import httpx
import structlog
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from config import settings
from feeds.provenance import provenance_fields
from pipeline import ExtractionConfigError, ExtractionTransientError, process_item
from qdrant_doctor.schema import validate_collection_schema

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Curated OSINT / Intelligence RSS Feeds
# ---------------------------------------------------------------------------
RSS_FEEDS: list[dict[str, str]] = [
    # ── German Defense / Bundeswehr ──
    {"name": "BMVg", "url": "https://www.bmvg.de/service/rss/de/17680/feed", "provider": "bmvg.de"},
    {"name": "Bundeswehr", "url": "https://www.bundeswehr.de/service/rss/de/517054/feed", "provider": "bundeswehr.de"},
    {"name": "Bundestag Verteidigung", "url": "https://www.bundestag.de/static/appdata/includes/rss/verteidigung.rss", "provider": "bundestag.de"},
    {"name": "Bundestag Auswaertiges", "url": "https://www.bundestag.de/static/appdata/includes/rss/auswaertiges.rss", "provider": "bundestag.de"},
    # Teaser-only (paywall), but keywords are extraction-rich.
    # Full knowledge via YouTube → NotebookLM → NLM pipeline.
    {"name": "SUV Sicherheit & Verteidigung", "url": "https://steady.page/de/suv/rss", "provider": "steady.page"},
    # ── Major News — World ──
    # Reuters/AP have no public RSS; Google News proxies provide equivalent coverage.
    {"name": "Reuters (Google)", "url": "https://news.google.com/rss/search?q=site:reuters.com+world&hl=en-US&gl=US&ceid=US:en", "provider": "reuters.com"},
    {"name": "BBC World", "url": "https://feeds.bbci.co.uk/news/world/rss.xml", "provider": "bbc.co.uk"},
    {"name": "Al Jazeera", "url": "https://www.aljazeera.com/xml/rss/all.xml", "provider": "aljazeera.com"},
    {"name": "AP News (Google)", "url": "https://news.google.com/rss/search?q=site:apnews.com+world+news&hl=en-US&gl=US&ceid=US:en", "provider": "apnews.com"},
    {"name": "France24", "url": "https://www.france24.com/en/rss", "provider": "france24.com"},
    # ── Defense / Military ──
    {"name": "The War Zone", "url": "https://www.thedrive.com/the-war-zone/feed", "provider": "thedrive.com"},
    {"name": "Defense One", "url": "https://www.defenseone.com/rss/all/", "provider": "defenseone.com"},
    {"name": "Breaking Defense", "url": "https://breakingdefense.com/feed/", "provider": "breakingdefense.com"},
    {"name": "Defense News", "url": "https://www.defensenews.com/arc/outboundfeeds/rss/?outputType=xml", "provider": "defensenews.com"},
    {"name": "War on the Rocks", "url": "https://warontherocks.com/feed/", "provider": "warontherocks.com"},
    {"name": "Aviation Week", "url": "https://aviationweek.com/rss.xml", "provider": "aviationweek.com"},
    {"name": "DoD News", "url": "https://www.defense.gov/DesktopModules/ArticleCS/RSS.ashx?ContentType=1&Site=945", "provider": "defense.gov"},
    # ── OSINT / Investigative ──
    {"name": "Bellingcat", "url": "https://www.bellingcat.com/feed/", "provider": "bellingcat.com"},
    {"name": "The Intercept", "url": "https://theintercept.com/feed/?rss", "provider": "theintercept.com"},
    {"name": "EUvsDisinfo", "url": "https://euvsdisinfo.eu/feed/", "provider": "euvsdisinfo.eu"},
    # ── Think Tanks ──
    {"name": "RAND Corporation", "url": "https://www.rand.org/pubs/research_reports.xml", "provider": "rand.org"},
    {"name": "CSIS", "url": "https://www.csis.org/rss.xml", "provider": "csis.org"},
    {"name": "Brookings", "url": "https://www.brookings.edu/feed/?post_type=article", "provider": "brookings.edu"},
    {"name": "Atlantic Council", "url": "https://www.atlanticcouncil.org/feed/", "provider": "atlanticcouncil.org"},
    {"name": "SWP Publications (DE)", "url": "https://www.swp-berlin.org/SWPPublications.xml", "provider": "swp-berlin.org"},
    {"name": "SWP Publications (EN)", "url": "https://www.swp-berlin.org/en/SWPPublications.xml", "provider": "swp-berlin.org"},
    {"name": "RUSI Commentary", "url": "https://www.rusi.org/rss/latest-commentary.xml", "provider": "rusi.org"},
    {"name": "RUSI Publications", "url": "https://www.rusi.org/rss/latest-publications.xml", "provider": "rusi.org"},
    # ── Government / IO ──
    {"name": "UN News", "url": "https://news.un.org/feed/subscribe/en/news/all/rss.xml", "provider": "news.un.org"},
    {"name": "US State Dept (Google)", "url": "https://news.google.com/rss/search?q=site:state.gov+%22press+releases%22&hl=en-US&gl=US&ceid=US:en", "provider": "state.gov"},
    {"name": "NATO (Google)", "url": "https://news.google.com/rss/search?q=site:nato.int&hl=en-US&gl=US&ceid=US:en", "provider": "nato.int"},
    {"name": "EU Parliament Security and Defence", "url": "https://www.europarl.europa.eu/rss/committee/sede/en.xml", "provider": "europarl.europa.eu"},
    {"name": "EU Parliament External Relations", "url": "https://www.europarl.europa.eu/rss/topic/903/en.xml", "provider": "europarl.europa.eu"},
    # ── Arms Control / Nonproliferation ──
    {"name": "SIPRI", "url": "https://www.sipri.org/rss/combined.xml", "provider": "sipri.org"},
    {"name": "Arms Control Association", "url": "https://www.armscontrol.org/rss.xml", "provider": "armscontrol.org"},
    # ── Conflict / Crisis ──
    {"name": "Crisis Group", "url": "https://www.crisisgroup.org/rss.xml", "provider": "crisisgroup.org"},
    {"name": "ReliefWeb", "url": "https://reliefweb.int/updates/rss.xml", "provider": "reliefweb.int"},
]

MAX_ENTRIES_PER_FEED = 15


def build_rss_payload(
    feed: dict,
    *,
    title: str,
    link: str,
    summary: str,
    published_at: str | None,
    content_hash: str,
    enrichment: dict | None,
) -> dict:
    """Pure RSS Qdrant payload builder (unit-testable, no I/O).

    provider is the feed's explicit canonical domain. published_at is passed
    through verbatim — None stays None (never ingestion time)."""
    return {
        **provenance_fields(
            source_type="rss",
            provider=feed["provider"],
            published_at=published_at,
        ),
        "source": "rss",
        "feed_name": feed["name"],
        "title": title,
        "url": link,
        "summary": (summary or "")[:1000],
        "published": published_at,
        "content_hash": content_hash,
        "ingested_at": datetime.now(UTC).isoformat(),
        "codebook_type": enrichment["codebook_type"] if enrichment else "other.unclassified",
        "entities": enrichment["entities"] if enrichment else [],
    }


def _content_hash(title: str, url: str) -> str:
    """Generate a deterministic hash for deduplication."""
    raw = f"{title.strip().lower()}|{url.strip().lower()}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _point_id_from_hash(content_hash: str) -> int:
    """Convert a hex hash into a 64-bit positive integer suitable for Qdrant point IDs."""
    return int(content_hash[:16], 16)


class RSSCollector:
    """Fetch RSS feeds, generate embeddings, and upsert into Qdrant."""

    def __init__(self, redis_client=None) -> None:
        self.qdrant = QdrantClient(url=settings.qdrant_url)
        self._redis = redis_client
        self._ensure_collection()

    # ------------------------------------------------------------------
    # Collection bootstrap
    # ------------------------------------------------------------------
    def _ensure_collection(self) -> None:
        """Create the Qdrant collection if it does not exist.

        If the collection already exists, its vector schema is validated against
        the active runtime mode (dense-only or hybrid) BEFORE any write occurs.
        Raises QdrantSchemaMismatch if the schema does not match.
        """
        enable_hybrid: bool = getattr(settings, "enable_hybrid", False)
        collections = [c.name for c in self.qdrant.get_collections().collections]
        if settings.qdrant_collection not in collections:
            self.qdrant.create_collection(
                collection_name=settings.qdrant_collection,
                vectors_config=VectorParams(
                    size=settings.embedding_dimensions,
                    distance=Distance.COSINE,
                ),
            )
            log.info("qdrant_collection_created", collection=settings.qdrant_collection)
        else:
            # Collection exists — validate schema before any write
            info = self.qdrant.get_collection(settings.qdrant_collection)
            validate_collection_schema(info, enable_hybrid=enable_hybrid)
            log.debug(
                "qdrant_schema_validated",
                collection=settings.qdrant_collection,
                enable_hybrid=enable_hybrid,
            )

    # ------------------------------------------------------------------
    # Embedding helper
    # ------------------------------------------------------------------
    async def _embed(self, text: str) -> list[float]:
        """Generate embedding vector via TEI (Text Embeddings Inference)."""
        async with httpx.AsyncClient(timeout=settings.http_timeout) as client:
            resp = await client.post(
                f"{settings.tei_embed_url}/embed",
                json={"inputs": text},
            )
            resp.raise_for_status()
            result = resp.json()
            # TEI returns [[...floats...]] for single input
            return result[0] if isinstance(result[0], list) else result

    # ------------------------------------------------------------------
    # Single feed processing
    # ------------------------------------------------------------------
    async def _process_feed(self, feed_meta: dict[str, str]) -> int:
        """Fetch and ingest a single RSS feed. Returns number of new items."""
        name = feed_meta["name"]
        url = feed_meta["url"]
        ingested = 0

        try:
            async with httpx.AsyncClient(
                timeout=settings.http_timeout,
                follow_redirects=True,
                headers={"User-Agent": "ODIN/WorldView RSS Collector (+https://github.com/Hunter5Thompson/OSINT)"},
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("rss_fetch_failed", feed=name, error=str(exc))
            return 0

        parsed = feedparser.parse(resp.text)
        if parsed.bozo and not parsed.entries:
            log.warning("rss_parse_failed", feed=name, error=str(parsed.bozo_exception))
            return 0

        entries = parsed.entries[:MAX_ENTRIES_PER_FEED]
        log.info("rss_feed_started", feed=name, entries=len(entries))

        points: list[PointStruct] = []
        for entry in entries:
            title = entry.get("title", "").strip()
            link = entry.get("link", "").strip()
            if not title or not link:
                continue

            chash = _content_hash(title, link)
            point_id = _point_id_from_hash(chash)

            # Deduplicate — skip if already stored
            existing = self.qdrant.retrieve(
                collection_name=settings.qdrant_collection,
                ids=[point_id],
            )
            if existing:
                continue

            # Build text for embedding
            summary = entry.get("summary", "")
            content = entry.get("content", [{}])[0].get("value", "") if entry.get("content") else ""
            embed_text = f"{title}\n{summary or content}"[:2000]

            published_parsed = entry.get("published_parsed")
            if published_parsed:
                try:
                    published_dt = datetime(*published_parsed[:6], tzinfo=UTC).isoformat()
                except Exception:
                    published_dt = None
            else:
                published_dt = None

            # Intelligence extraction. Transient/config errors skip Qdrant upsert
            # so the item is retried on the next source re-fetch (Hash-Dedup doesn't trip).
            try:
                enrichment = await process_item(
                    title=title,
                    text=embed_text,
                    url=link,
                    source="rss",
                    settings=settings,
                    redis_client=self._redis,
                )
            except ExtractionTransientError as exc:
                log.warning("extraction_skipped_transient", url=link, error=str(exc))
                continue
            except ExtractionConfigError as exc:
                log.error("extraction_skipped_config", url=link, error=str(exc))
                continue

            try:
                vector = await self._embed(embed_text)
            except httpx.HTTPError as exc:
                log.warning("embedding_failed", title=title[:80], error=str(exc))
                continue

            points.append(
                PointStruct(
                    id=point_id,
                    vector=vector,
                    payload=build_rss_payload(
                        feed_meta,
                        title=title,
                        link=link,
                        summary=summary or content,
                        published_at=published_dt,
                        content_hash=chash,
                        enrichment=enrichment,
                    ),
                )
            )
            ingested += 1

        if points:
            self.qdrant.upsert(
                collection_name=settings.qdrant_collection,
                points=points,
            )

        return ingested

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    async def collect(self) -> None:
        """Fetch all RSS feeds and ingest new articles."""
        log.info("rss_collection_started", feed_count=len(RSS_FEEDS))
        total = 0
        start = time.monotonic()

        for feed_meta in RSS_FEEDS:
            try:
                count = await self._process_feed(feed_meta)
                if count:
                    log.info("rss_feed_ingested", feed=feed_meta["name"], new_items=count)
                total += count
            except Exception:
                log.exception("rss_feed_error", feed=feed_meta["name"])

        elapsed = round(time.monotonic() - start, 2)
        log.info("rss_collection_finished", total_new=total, elapsed_seconds=elapsed)
