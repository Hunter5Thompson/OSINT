"""GDELT Global Knowledge Graph Collector — queries GDELT for geopolitically relevant events."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from config import settings
from pipeline import (
    ExtractionConfigError,
    ExtractionTransientError,
    Neo4jWriteError,
    content_hash,
    process_item,
)
from qdrant_doctor.schema import validate_collection_schema

log = structlog.get_logger(__name__)


def _normalize_seendate(seendate: str | None) -> str | None:
    """GDELT ArtList seendate ('20260610T120000Z' or '20260610') -> ISO-8601 UTC,
    or None when empty/malformed. Never fabricates: an unparseable value returns
    None so the pipeline's _resolve_timeline falls back to the ingested basis."""
    if not seendate or not isinstance(seendate, str):
        return None
    s = seendate.strip()
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=UTC).isoformat()
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# GDELT query templates — each targets a different geopolitical theme
# ---------------------------------------------------------------------------
GDELT_QUERIES: list[dict[str, str]] = [
    {
        "name": "conflict_military",
        "query": "conflict OR military OR warfare OR troops",
    },
    {
        "name": "nuclear_weapons",
        "query": "nuclear weapon OR nuclear test OR ICBM OR missile launch",
    },
    {
        "name": "territorial_disputes",
        "query": "territorial dispute OR border clash OR annexation OR sovereignty",
    },
    {
        "name": "sanctions_diplomacy",
        "query": "sanctions OR diplomatic crisis OR embassy OR ceasefire",
    },
    {
        "name": "cyber_warfare",
        "query": "cyberattack OR cyber warfare OR hacking OR critical infrastructure attack",
    },
    {
        "name": "naval_movements",
        "query": "naval exercise OR aircraft carrier OR fleet deployment OR maritime security",
    },
    {
        "name": "arms_trade",
        "query": "arms deal OR weapons shipment OR defense contract OR military aid",
    },
]

GDELT_BASE_URL = "https://api.gdeltproject.org/api/v2/doc/doc"


def _point_id_from_hash(content_hash: str) -> int:
    return int(content_hash[:16], 16)


class GDELTCollector:
    """Fetch geopolitically relevant events from GDELT GKG and ingest into Qdrant."""

    def __init__(self, redis_client=None) -> None:
        self.qdrant = QdrantClient(url=settings.qdrant_url)
        self._redis = redis_client
        self._ensure_collection()

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

    async def _embed(self, text: str) -> list[float]:
        async with httpx.AsyncClient(timeout=settings.http_timeout) as client:
            resp = await client.post(
                f"{settings.tei_embed_url}/embed",
                json={"inputs": text},
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list) and data:
                return data[0] if isinstance(data[0], list) else data
            return data

    async def _fetch_query(self, query_meta: dict[str, str]) -> list[dict[str, Any]]:
        """Execute a single GDELT query and return article list."""
        params = {
            "query": query_meta["query"],
            "mode": "ArtList",
            "maxrecords": "50",
            "format": "json",
        }
        try:
            async with httpx.AsyncClient(
                timeout=settings.http_timeout,
                follow_redirects=True,
            ) as client:
                resp = await client.get(GDELT_BASE_URL, params=params)
                resp.raise_for_status()
                data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("gdelt_fetch_failed", query=query_meta["name"], error=str(exc))
            return []

        articles = data.get("articles", [])
        return articles

    async def _ingest_articles(
        self, articles: list[dict[str, Any]], query_name: str
    ) -> int:
        """Embed and upsert a batch of GDELT articles. Returns count of new items."""
        points: list[PointStruct] = []
        for article in articles:
            title = article.get("title", "").strip()
            url = article.get("url", "").strip()
            if not title or not url:
                continue

            chash = content_hash(title, url)
            point_id = _point_id_from_hash(chash)

            # Deduplicate — a transient Qdrant fault must not abandon the accumulated batch.
            try:
                existing = self.qdrant.retrieve(
                    collection_name=settings.qdrant_collection,
                    ids=[point_id],
                )
            except Exception as exc:  # noqa: BLE001 — skip this item, keep the batch
                log.warning("gdelt_dedup_retrieve_failed", url=url, error=str(exc))
                continue
            if existing:
                continue

            seendate = article.get("seendate", "")
            domain = article.get("domain", "")
            language = article.get("language", "")
            source_country = article.get("sourcecountry", "")

            embed_text = f"{title}"[:2000]

            # Intelligence extraction. Transient/config errors skip Qdrant upsert
            # so the item is retried on the next source re-fetch (Hash-Dedup doesn't trip).
            try:
                enrichment = await process_item(
                    title=title,
                    text=embed_text,
                    url=url,
                    source="gdelt",
                    settings=settings,
                    redis_client=self._redis,
                    observed_at=_normalize_seendate(seendate),
                    content_hash=chash,
                    raise_on_write_error=True,
                )
            except ExtractionTransientError as exc:
                log.warning("extraction_skipped_transient", url=url, error=str(exc))
                continue
            except ExtractionConfigError as exc:
                log.error("extraction_skipped_config", url=url, error=str(exc))
                continue
            except Neo4jWriteError as exc:
                # Graph write failed — skip the Qdrant upsert so the dedup point is not
                # minted; the still-fresh article is retried on the next fetch.
                log.warning("gdelt_neo4j_write_skipped", url=url, error=str(exc))
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
                    payload={
                        "source": "gdelt",
                        "gdelt_query": query_name,
                        "title": title,
                        "url": url,
                        "domain": domain,
                        "language": language,
                        "source_country": source_country,
                        "seen_date": seendate,
                        "content_hash": chash,
                        "ingested_at": datetime.now(UTC).isoformat(),
                        "codebook_type": (
                            enrichment["codebook_type"] if enrichment else "other.unclassified"
                        ),
                        "entities": enrichment["entities"] if enrichment else [],
                    },
                )
            )

        if points:
            self.qdrant.upsert(
                collection_name=settings.qdrant_collection,
                points=points,
            )
        return len(points)

    async def collect(self) -> None:
        """Run all GDELT queries and ingest results."""
        log.info("gdelt_collection_started", query_count=len(GDELT_QUERIES))
        total = 0
        start = time.monotonic()

        for query_meta in GDELT_QUERIES:
            try:
                articles = await self._fetch_query(query_meta)
                if articles:
                    count = await self._ingest_articles(articles, query_meta["name"])
                    log.info(
                        "gdelt_query_ingested",
                        query=query_meta["name"],
                        fetched=len(articles),
                        new_items=count,
                    )
                    total += count
            except Exception:
                log.exception("gdelt_query_error", query=query_meta["name"])

        elapsed = round(time.monotonic() - start, 2)
        log.info("gdelt_collection_finished", total_new=total, elapsed_seconds=elapsed)
