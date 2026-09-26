"""Client wiring shared by the scheduler job and the gdelt_raw CLI.

Both paths must write identically; building them in two places let the CLI
miss TEI batching (PR #109) and made backfill ~3x slower per slice."""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx
import redis.asyncio as aioredis
from qdrant_client import AsyncQdrantClient

from config import settings
from gdelt_raw.state import GDELTState
from gdelt_raw.writers.neo4j_writer import Neo4jWriter
from gdelt_raw.writers.qdrant_writer import (
    QdrantWriter,
    default_tei_embed,
    default_tei_embed_batch,
)
from graph_integrity.spatial_normalizer import load_active_normalization_index


@dataclass
class GDELTClients:
    redis: aioredis.Redis
    state: GDELTState
    neo4j: Neo4jWriter
    qdrant: QdrantWriter
    tei_client: httpx.AsyncClient

    async def aclose(self) -> None:
        try:
            await self.neo4j.close()
        finally:
            try:
                await self.qdrant.close()
            finally:
                try:
                    await self.tei_client.aclose()
                finally:
                    await self.redis.aclose()


async def open_clients() -> GDELTClients:
    spatial_index = load_active_normalization_index(
        settings.spatial_catalog_path,
        crosswalk_path=settings.spatial_country_crosswalk_path,
    )
    r = aioredis.from_url(
        os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        decode_responses=True,
    )
    neo4j = Neo4jWriter(
        uri=os.getenv("NEO4J_URL", "bolt://localhost:7687"),
        user=os.getenv("NEO4J_USER", "neo4j"),
        password=os.getenv("NEO4J_PASSWORD", ""),
        spatial_index=spatial_index,
    )
    qdrant_client = AsyncQdrantClient(
        url=os.getenv("QDRANT_URL", "http://localhost:6333")
    )
    tei_url = os.getenv("TEI_EMBED_URL", "http://localhost:8001")
    tei_client = httpx.AsyncClient(timeout=60.0)

    async def embed(text: str) -> list[float]:
        return await default_tei_embed(text, tei_url=tei_url)

    async def embed_batch(texts: list[str]) -> list[list[float]]:
        return await default_tei_embed_batch(texts, tei_url=tei_url, client=tei_client)

    qdrant = QdrantWriter(
        client=qdrant_client,
        embed=embed,
        embed_batch=embed_batch,
        collection=settings.qdrant_collection,
        embedding_dimensions=settings.embedding_dimensions,
        enable_hybrid=settings.enable_hybrid,
        spatial_index=spatial_index,
    )
    return GDELTClients(redis=r, state=GDELTState(r), neo4j=neo4j, qdrant=qdrant,
                        tei_client=tei_client)
