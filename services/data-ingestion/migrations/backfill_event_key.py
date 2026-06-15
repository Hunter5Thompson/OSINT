"""Backfill event_key on live-pipeline :Event nodes (NOT :GDELTEvent) and merge
duplicates that collapse onto the same key, with parity to pipeline._event_key.

IDEMPOTENT BY RECOMPUTE: every run fetches ALL live :Event (not just event_key IS NULL),
recomputes the expected key in Python, (re)sets it, and merges any duplicate groups by the
computed key. So a crash after a partial apply self-heals on re-run — an `IS NULL` filter
would go blind to already-keyed survivors and leave duplicate groups unmerged.

Run with --dry-run first; it prints counts and writes nothing.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field

import structlog

from pipeline import _event_key, content_hash

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class EventRow:
    node_id: int
    title: str
    codebook_type: str
    doc_url: str
    doc_title: str

    def event_key(self) -> str:
        return _event_key(content_hash(self.doc_title, self.doc_url),
                          self.codebook_type, self.title)


@dataclass
class MergeGroup:
    key: str
    survivor_id: int
    loser_ids: list[int]


@dataclass
class BackfillPlan:
    assignments: dict[int, str]            # node_id -> event_key
    merges: list[MergeGroup] = field(default_factory=list)

    def key_for(self, node_id: int) -> str:
        return self.assignments[node_id]

    @property
    def total(self) -> int:
        return len(self.assignments)

    @property
    def group_count(self) -> int:
        return len(self.merges)

    @property
    def duplicate_count(self) -> int:
        return sum(len(m.loser_ids) for m in self.merges)


def plan_backfill(rows: list[EventRow]) -> BackfillPlan:
    by_key: dict[str, list[int]] = {}
    assignments: dict[int, str] = {}
    for r in rows:
        k = r.event_key()
        assignments[r.node_id] = k
        by_key.setdefault(k, []).append(r.node_id)
    merges = []
    for k, ids in by_key.items():
        if len(ids) > 1:
            ordered = sorted(ids)            # lowest node_id = survivor (deterministic)
            merges.append(MergeGroup(key=k, survivor_id=ordered[0], loser_ids=ordered[1:]))
    return BackfillPlan(assignments=assignments, merges=merges)


# Fetch ALL live :Event (NOT :GDELTEvent) WITH document context — regardless of whether
# event_key is already set — so a re-run after a partial/crashed apply still sees every
# node and every duplicate group.
_FETCH = (
    "MATCH (d:Document)-[:DESCRIBES]->(ev:Event) "
    "WHERE NOT ev:GDELTEvent "
    "RETURN id(ev) AS node_id, ev.title AS title, "
    "       coalesce(ev.codebook_type,'other.unclassified') AS codebook_type, "
    "       d.url AS doc_url, coalesce(d.title,'') AS doc_title"
)
_SET_KEY = "MATCH (ev) WHERE id(ev) = $node_id SET ev.event_key = $key"
# Preflight before applying event_key_unique.cypher — MUST return zero rows.
_PREFLIGHT_DUP_KEYS = (
    "MATCH (ev:Event) WHERE NOT ev:GDELTEvent "
    "WITH ev.event_key AS k, count(*) AS c "
    "WHERE k IS NOT NULL AND c > 1 "
    "RETURN k AS event_key, c AS count ORDER BY c DESC"
)
_MERGE = (
    "MATCH (s) WHERE id(s) = $survivor_id "
    "MATCH (l) WHERE id(l) = $loser_id "
    "CALL apoc.refactor.mergeNodes([s, l], {properties:'discard', mergeRels:true}) "
    "YIELD node RETURN id(node)"
)


async def _fetch_rows(driver) -> list[EventRow]:
    async with driver.session() as s:
        res = await s.run(_FETCH)
        return [EventRow(r["node_id"], r["title"] or "", r["codebook_type"],
                         r["doc_url"], r["doc_title"]) async for r in res]


async def run(driver, *, dry_run: bool) -> BackfillPlan:
    rows = await _fetch_rows(driver)
    plan = plan_backfill(rows)
    log.info("backfill_event_key_plan", total=plan.total,
             groups=plan.group_count, duplicates=plan.duplicate_count, dry_run=dry_run)
    if dry_run:
        return plan
    merged_losers = {lid for m in plan.merges for lid in m.loser_ids}
    async with driver.session() as s:
        for m in plan.merges:                     # collapse duplicate groups first
            for loser in m.loser_ids:
                await s.run(_MERGE, survivor_id=m.survivor_id, loser_id=loser)
        for node_id, key in plan.assignments.items():
            if node_id in merged_losers:
                continue                          # gone — merged into its survivor
            await s.run(_SET_KEY, node_id=node_id, key=key)   # (re)set; no-op if already correct
    return plan


async def verify_no_duplicate_keys(driver) -> list[tuple[str, int]]:
    """Preflight before applying event_key_unique.cypher — MUST return []."""
    async with driver.session() as s:
        res = await s.run(_PREFLIGHT_DUP_KEYS)
        return [(r["event_key"], r["count"]) async for r in res]


def _build_driver():
    import neo4j

    from config import settings
    return neo4j.AsyncGraphDatabase.driver(
        settings.neo4j_url, auth=(settings.neo4j_user, settings.neo4j_password))


async def _main(dry_run: bool) -> None:
    driver = _build_driver()
    try:
        await run(driver, dry_run=dry_run)
        if not dry_run:
            dups = await verify_no_duplicate_keys(driver)
            if dups:
                log.error("backfill_event_key_dups_remain", groups=len(dups), sample=dups[:5])
            else:
                log.info("backfill_event_key_verified", duplicate_keys=0)
    finally:
        await driver.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    args = ap.parse_args()
    asyncio.run(_main(dry_run=not args.apply))
