"""One-shot: backfill timeline_at on existing GDELT events.

Run manually (NOT wired into the scheduler), ideally against a DB copy first:
    cd services/data-ingestion && uv run python -m gdelt_raw.migrations.run_phase3

Idempotent: re-running only touches events whose timeline_at IS NULL. The driver
URI is the BOLT endpoint (AsyncGraphDatabase), mirroring gdelt_raw/cli.py — note
the live pipeline writes over HTTP (neo4j_http_url) but the bolt driver is what
the GDELT subsystem already uses for sessions.
"""

import asyncio
import os

from neo4j import AsyncGraphDatabase

from gdelt_raw.migrations.apply import apply_phase3


async def main() -> None:
    driver = AsyncGraphDatabase.driver(
        os.getenv("NEO4J_URL", "bolt://localhost:7687"),
        auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "")),
    )
    try:
        await apply_phase3(driver)
    finally:
        await driver.close()


if __name__ == "__main__":
    asyncio.run(main())
