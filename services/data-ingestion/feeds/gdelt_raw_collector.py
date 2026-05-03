"""Thin scheduler wrapper — delegates to gdelt_raw.run.run_forward."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import redis.asyncio as aioredis
import structlog
from qdrant_client import AsyncQdrantClient

from config import Settings
from gdelt_raw.config import get_settings
from gdelt_raw.run import run_forward
from gdelt_raw.state import GDELTState
from gdelt_raw.writers.neo4j_writer import Neo4jWriter
from gdelt_raw.writers.qdrant_writer import QdrantWriter, default_tei_embed

log = structlog.get_logger(__name__)


async def run_once() -> None:
    settings = get_settings()
    r = aioredis.from_url(
        os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        decode_responses=True,
    )
    state = GDELTState(r)
    neo4j = Neo4jWriter(
        uri=os.getenv("NEO4J_URL", "bolt://localhost:7687"),
        user=os.getenv("NEO4J_USER", "neo4j"),
        password=os.getenv("NEO4J_PASSWORD", ""),
    )
    qdrant_client = AsyncQdrantClient(
        url=os.getenv("QDRANT_URL", "http://localhost:6333")
    )
    tei_url = os.getenv("TEI_EMBED_URL", "http://localhost:8001")

    async def embed(text: str) -> list[float]:
        return await default_tei_embed(text, tei_url=tei_url)

    qdrant = QdrantWriter(
        client=qdrant_client,
        embed=embed,
        collection=Settings(_env_file=None).qdrant_collection,
    )
    try:
        await run_forward(state, neo4j, qdrant, Path(settings.parquet_path))
    finally:
        await neo4j.close()


def collect() -> None:
    """Sync entry-point for APScheduler."""
    asyncio.run(run_once())
