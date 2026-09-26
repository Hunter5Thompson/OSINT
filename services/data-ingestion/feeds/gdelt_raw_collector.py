"""Thin scheduler wrapper — delegates to gdelt_raw.run.run_forward."""

from __future__ import annotations

import asyncio
from pathlib import Path

import structlog

from gdelt_raw.clients import open_clients
from gdelt_raw.config import get_settings
from gdelt_raw.run import run_forward

log = structlog.get_logger(__name__)


async def run_once() -> None:
    clients = await open_clients()
    try:
        await clients.neo4j.ensure_schema()
        await run_forward(clients.state, clients.neo4j, clients.qdrant,
                          Path(get_settings().parquet_path))
    finally:
        await clients.aclose()


def collect() -> None:
    """Sync entry-point for APScheduler."""
    asyncio.run(run_once())
