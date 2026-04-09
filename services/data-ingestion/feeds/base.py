"""BaseCollector — shared abstraction for all Hugin P0 collectors."""

from __future__ import annotations

import asyncio
import hashlib
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from config import Settings

log = structlog.get_logger(__name__)


class BaseCollector(ABC):
    """Gemeinsame Logik für alle Hugin Collectors.

    Subclasses implement `collect()` with source-specific fetch/parse/ingest.
    """

    def __init__(self, settings: Settings, redis_client: Any | None = None) -> None:
        self.settings = settings
        self.redis = redis_client
        self.qdrant = QdrantClient(url=settings.qdrant_url)
        self.http = httpx.AsyncClient(timeout=settings.http_timeout)
        self._collection_ready = False

    async def _ensure_collection(self) -> None:
        if self._collection_ready:
            return
        collections = await asyncio.to_thread(
            lambda: self.qdrant.get_collections().collections
        )
        if not any(c.name == self.settings.qdrant_collection for c in collections):
            await asyncio.to_thread(
                lambda: self.qdrant.create_collection(
                    collection_name=self.settings.qdrant_collection,
                    vectors_config=VectorParams(
                        size=self.settings.embedding_dimensions,
                        distance=Distance.COSINE,
                    ),
                )
            )
            log.info("qdrant_collection_created", collection=self.settings.qdrant_collection)
        self._collection_ready = True

    async def _embed(self, text: str) -> list[float]:
        resp = await self.http.post(
            f"{self.settings.tei_embed_url}/embed",
            json={"inputs": text, "truncate": True},
        )
        resp.raise_for_status()
        data = resp.json()
        return data[0] if isinstance(data[0], list) else data

    def _content_hash(self, *parts: str) -> str:
        raw = "|".join(p.lower().strip() for p in parts)
        return hashlib.sha256(raw.encode()).hexdigest()

    def _point_id(self, content_hash: str) -> int:
        return int(content_hash[:16], 16)

    async def _dedup_check(self, point_id: int) -> bool:
        existing = await asyncio.to_thread(
            self.qdrant.retrieve,
            collection_name=self.settings.qdrant_collection,
            ids=[point_id],
        )
        return len(existing) > 0

    async def _batch_upsert(self, points: list[PointStruct]) -> None:
        if not points:
            return
        await asyncio.to_thread(
            self.qdrant.upsert,
            collection_name=self.settings.qdrant_collection,
            points=points,
        )
        log.info("qdrant_batch_upserted", count=len(points))

    async def _build_point(
        self, text: str, payload: dict, content_hash: str
    ) -> PointStruct:
        vector = await self._embed(text)
        point_id = self._point_id(content_hash)
        payload["content_hash"] = content_hash
        payload["ingested_at"] = datetime.now(timezone.utc).isoformat()
        return PointStruct(id=point_id, vector=vector, payload=payload)

    @abstractmethod
    async def collect(self) -> None: ...

    async def close(self) -> None:
        await self.http.aclose()
