"""One-shot: backfill timeline_at on existing GDELT events.

Run manually (NOT wired into the scheduler), ideally against a DB copy first:
    cd services/data-ingestion && uv run python -m gdelt_raw.migrations.run_phase3

Idempotent: re-running only touches events whose timeline_at IS NULL. Connection
settings come from `config.Settings` (pydantic-settings), so the project's `.env`
is honored — neo4j_url is the BOLT endpoint for AsyncGraphDatabase (the live
pipeline writes over HTTP, but the GDELT subsystem uses the bolt driver here).
"""

import asyncio

from neo4j import AsyncGraphDatabase

from config import settings
from gdelt_raw.migrations.apply import apply_phase3


async def main() -> None:
    driver = AsyncGraphDatabase.driver(
        settings.neo4j_url,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
    try:
        await apply_phase3(driver)
    finally:
        await driver.close()


if __name__ == "__main__":
    asyncio.run(main())
