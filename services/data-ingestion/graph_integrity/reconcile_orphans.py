"""Lossy reconcile: find Qdrant points whose source URL has no Neo4j :Document and
re-run extraction from the stored title so the graph node is (re)created idempotently.

LOSSY — Qdrant stores only the title, not the original full text. The T1 forward fix is
the real guarantee; this heals legacy orphans only. Run with --dry-run first.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass

import structlog

from config import settings
from pipeline import content_hash, process_item

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class OrphanCandidate:
    point_id: int
    title: str
    url: str


def find_orphans(
    points: list[OrphanCandidate], existing_doc_urls: set[str]
) -> list[OrphanCandidate]:
    """Pure: points whose url is absent from the set of Document urls in Neo4j."""
    return [p for p in points if p.url and p.url not in existing_doc_urls]


async def _scroll_points(qdrant) -> list[OrphanCandidate]:
    out: list[OrphanCandidate] = []
    offset = None
    while True:
        batch, offset = qdrant.scroll(
            collection_name=settings.qdrant_collection,
            with_payload=True, limit=512, offset=offset,
        )
        for p in batch:
            pl = p.payload or {}
            if pl.get("url") and pl.get("title"):
                out.append(OrphanCandidate(p.id, pl["title"], pl["url"]))
        if offset is None:
            break
    return out


async def _existing_doc_urls(driver, urls: list[str]) -> set[str]:
    async with driver.session() as s:
        res = await s.run(
            "MATCH (d:Document) WHERE d.url IN $urls RETURN d.url AS url", urls=urls)
        return {r["url"] async for r in res}


async def run(qdrant, driver, *, dry_run: bool) -> list[OrphanCandidate]:
    points = await _scroll_points(qdrant)
    existing = await _existing_doc_urls(driver, [p.url for p in points])
    orphans = find_orphans(points, existing)
    log.info("reconcile_orphans_plan", total=len(points), orphans=len(orphans), dry_run=dry_run)
    if dry_run:
        return orphans
    for o in orphans:
        try:
            await process_item(
                title=o.title, text=o.title, url=o.url, source="reconcile",
                settings=settings, content_hash=content_hash(o.title, o.url),
                raise_on_write_error=True,
            )
        except Exception as exc:  # noqa: BLE001 — keep healing the rest
            log.warning("reconcile_item_failed", url=o.url, error=str(exc))
    return orphans


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="re-ingest orphans (default: dry-run)")
    args = ap.parse_args()

    import neo4j
    from qdrant_client import QdrantClient

    qc = QdrantClient(url=settings.qdrant_url)
    drv = neo4j.AsyncGraphDatabase.driver(
        settings.neo4j_url, auth=(settings.neo4j_user, settings.neo4j_password))

    async def _go():
        try:
            await run(qc, drv, dry_run=not args.apply)
        finally:
            await drv.close()

    asyncio.run(_go())
