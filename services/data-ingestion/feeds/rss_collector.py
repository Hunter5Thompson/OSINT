"""RSS Feed Collector — fetches OSINT/intelligence RSS feeds, embeds, and upserts to Qdrant."""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from typing import Any

import feedparser
import httpx
import structlog
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from config import settings

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Curated OSINT / Intelligence RSS Feeds
# ---------------------------------------------------------------------------
RSS_FEEDS: list[dict[str, str]] = [
    # Major News — World
    {"name": "Reuters World", "url": "https://feeds.reuters.com/Reuters/worldNews"},
    {"name": "BBC World", "url": "https://feeds.bbci.co.uk/news/world/rss.xml"},
    {"name": "Al Jazeera", "url": "https://www.aljazeera.com/xml/rss/all.xml"},
    {"name": "AP News", "url": "https://rsshub.app/apnews/topics/world-news"},
    {"name": "France24", "url": "https://www.france24.com/en/rss"},
    # Defense / Military
    {"name": "The War Zone", "url": "https://www.thedrive.com/the-war-zone/feed"},
    {"name": "Defense One", "url": "https://www.defenseone.com/rss/"},
    {"name": "Breaking Defense", "url": "https://breakingdefense.com/feed/"},
    {"name": "Defense News", "url": "https://www.defensenews.com/arc/outboundfeeds/rss/?outputType=xml"},
    {"name": "Janes", "url": "https://www.janes.com/feeds/news"},
    {"name": "Aviation Week", "url": "https://aviationweek.com/rss.xml"},
    # OSINT / Investigative
    {"name": "Bellingcat", "url": "https://www.bellingcat.com/feed/"},
    {"name": "The Intercept", "url": "https://theintercept.com/feed/?rss"},
    # Think Tanks
    {"name": "RUSI", "url": "https://rusi.org/rss.xml"},
    {"name": "IISS", "url": "https://www.iiss.org/rss"},
    {"name": "RAND Corporation", "url": "https://www.rand.org/content/rand/pubs/feed.xml"},
    {"name": "CSIS", "url": "https://www.csis.org/rss.xml"},
    {"name": "Brookings", "url": "https://www.brookings.edu/feed/"},
    {"name": "Carnegie Endowment", "url": "https://carnegieendowment.org/rss/solr/?lang=en"},
    # Government / IO
    {"name": "US State Dept", "url": "https://www.state.gov/rss-feed/press-releases/feed/"},
    {"name": "NATO News", "url": "https://www.nato.int/cps/en/natohq/news.xml"},
    {"name": "UN News", "url": "https://news.un.org/feed/subscribe/en/news/all/rss.xml"},
    # Arms Control / Nonproliferation
    {"name": "SIPRI", "url": "https://www.sipri.org/rss.xml"},
    {"name": "Arms Control Association", "url": "https://www.armscontrol.org/rss.xml"},
    # Conflict / Crisis
    {"name": "Crisis Group", "url": "https://www.crisisgroup.org/rss.xml"},
    {"name": "Liveuamap", "url": "https://liveuamap.com/rss"},
    {"name": "ACLED", "url": "https://acleddata.com/feed/"},
]


def _content_hash(title: str, url: str) -> str:
    """Generate a deterministic hash for deduplication."""
    raw = f"{title.strip().lower()}|{url.strip().lower()}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _point_id_from_hash(content_hash: str) -> int:
    """Convert a hex hash into a 64-bit positive integer suitable for Qdrant point IDs."""
    return int(content_hash[:16], 16)


class RSSCollector:
    """Fetch RSS feeds, generate embeddings, and upsert into Qdrant."""

    def __init__(self) -> None:
        self.qdrant = QdrantClient(url=settings.qdrant_url)
        self._ensure_collection()

    # ------------------------------------------------------------------
    # Collection bootstrap
    # ------------------------------------------------------------------
    def _ensure_collection(self) -> None:
        """Create the Qdrant collection if it does not exist."""
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

        points: list[PointStruct] = []
        for entry in parsed.entries:
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

            published = entry.get("published", "")
            published_parsed = entry.get("published_parsed")
            if published_parsed:
                try:
                    published_dt = datetime(*published_parsed[:6], tzinfo=timezone.utc).isoformat()
                except Exception:
                    published_dt = published
            else:
                published_dt = published or datetime.now(timezone.utc).isoformat()

            try:
                vector = await self._embed(embed_text)
            except httpx.HTTPError as exc:
                log.warning("embedding_failed", title=title[:80], error=str(exc))
                continue

            points.append(
                PointStruct(
                    id=point_id,
                    vector=vector,
                    payload={
                        "source": "rss",
                        "feed_name": name,
                        "title": title,
                        "url": link,
                        "summary": (summary or content)[:1000],
                        "published": published_dt,
                        "content_hash": chash,
                        "ingested_at": datetime.now(timezone.utc).isoformat(),
                    },
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
