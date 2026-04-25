"""Apply GDELT schema migrations with Source-duplicate preflight."""

from __future__ import annotations

from pathlib import Path

import structlog

log = structlog.get_logger(__name__)

MIGRATIONS_DIR = Path(__file__).parent

SOURCE_DUP_PREFLIGHT_QUERY = """
MATCH (s:Source)
WITH s.name AS name, count(*) AS c
WHERE name IS NOT NULL AND c > 1
RETURN name, c ORDER BY c DESC
"""


def read_cypher_file(name: str) -> str:
    return (MIGRATIONS_DIR / name).read_text()


async def check_source_duplicates(driver) -> list[tuple[str, int]]:
    async with driver.session() as session:
        result = await session.run(SOURCE_DUP_PREFLIGHT_QUERY)
        rows = [(r["name"], r["c"]) async for r in result]
    return rows


async def apply_phase1(driver) -> None:
    """Apply scoped constraints. Aborts if :Source has duplicates."""
    dups = await check_source_duplicates(driver)
    if dups:
        raise RuntimeError(
            f"Cannot apply source_name_unique — {len(dups)} duplicates found: {dups[:5]}"
        )
    statements = [
        s.strip() for s in read_cypher_file("phase1_constraints.cypher").split(";")
        if s.strip()
    ]
    async with driver.session() as session:
        for stmt in statements:
            await session.run(stmt)
            log.info("migration_applied", stmt=stmt[:60])


async def apply_phase2(driver) -> None:
    statements = [
        s.strip() for s in read_cypher_file("phase2_indexes.cypher").split(";")
        if s.strip()
    ]
    async with driver.session() as session:
        for stmt in statements:
            await session.run(stmt)
            log.info("index_applied", stmt=stmt[:60])
