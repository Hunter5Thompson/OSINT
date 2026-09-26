"""Conservative Event key repair, dry by default.

Pause all writers and take a tested offline dump before applying. Existing keys
are immutable: Document titles can change, and collectors can supply their own
content hash. A shared API URL is not an event identity. Ambiguous legacy events
receive unique archival keys and an explicit unresolved marker; they are never
silently merged. Only equal extraction properties (except updated_at/event_key)
with equal document context qualify for merging. Relationship multiplicity and
properties are preserved. Original nodes/edges and the plan are fsynced to an
exclusive archive before any writes. Every merge additionally retains original
node properties as JSON on the survivor. Batch transactions fail on stale input.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import structlog

from pipeline import _event_key, content_hash

log = structlog.get_logger(__name__)


def _json(value: Any) -> str:
    return json.dumps(value, default=str, sort_keys=True, ensure_ascii=False)


@dataclass(frozen=True)
class EventRow:
    node_id: int
    title: str
    codebook_type: str
    doc_url: str
    doc_title: str
    existing_key: str | None = None
    properties: dict[str, Any] = field(default_factory=dict)
    element_id: str = ""
    labels: tuple[str, ...] = ("Event",)
    properties_json: str = ""

    def event_key(self) -> str:
        if not self.doc_url or not self.doc_url.strip():
            raise ValueError(f"Event {self.node_id}: missing document URL")
        return _event_key(content_hash(self.doc_title, self.doc_url),
                          self.codebook_type, self.title)

    def facts(self) -> str:
        return _json({k: v for k, v in self.properties.items()
                      if k not in {"event_key", "updated_at"} and not k.startswith("repair_")})

    def shared_endpoint(self) -> bool:
        return "/featureserver/" in self.doc_url.lower() and "#eventid=" not in self.doc_url


@dataclass
class MergeGroup:
    key: str
    survivor_id: int
    loser_ids: list[int]


@dataclass
class BackfillPlan:
    assignments: dict[int, str]
    merges: list[MergeGroup] = field(default_factory=list)
    unresolved: dict[int, str] = field(default_factory=dict)

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


def _legacy_key(row: EventRow) -> str:
    identity = row.element_id or str(row.node_id)
    return "legacy:" + hashlib.sha256(identity.encode()).hexdigest()


def plan_backfill(rows: list[EventRow]) -> BackfillPlan:
    unique: dict[int, EventRow] = {}
    canonical: dict[str, list[EventRow]] = {}
    for row in rows:
        key = row.event_key()
        if row.node_id in unique:
            old = unique[row.node_id]
            if old.event_key() != key or old.facts() != row.facts():
                raise ValueError(f"Event {row.node_id}: conflicting document context")
            continue
        unique[row.node_id] = row
        canonical.setdefault(key, []).append(row)

    plan = BackfillPlan({})
    occupied: dict[str, list[EventRow]] = {}
    for row in unique.values():
        if row.existing_key:
            occupied.setdefault(row.existing_key, []).append(row)
    for key, keyed in occupied.items():
        if len(keyed) > 1 and (len({(r.event_key(), r.facts()) for r in keyed}) > 1
                              or any(r.shared_endpoint() for r in keyed)):
            raise ValueError(f"Conflicting existing key: {key}")

    for key, members in canonical.items():
        facts: dict[str, list[EventRow]] = {}
        for row in members:
            if row.shared_endpoint():
                plan.assignments[row.node_id] = row.existing_key or _legacy_key(row)
                plan.unresolved[row.node_id] = "shared_api_endpoint_without_record_identity"
            else:
                facts.setdefault(row.facts(), []).append(row)
        for equal in facts.values():
            existing = {r.existing_key for r in equal if r.existing_key}
            if len(existing) > 1:
                # Distinct supplied source hashes may represent different records.
                for row in equal:
                    plan.assignments[row.node_id] = row.existing_key or _legacy_key(row)
                    plan.unresolved[row.node_id] = "distinct_existing_source_keys"
                continue
            if existing:
                target = next(iter(existing))
            elif len(facts) == 1 and key not in occupied:
                target = key
            else:
                target = _legacy_key(min(equal, key=lambda r: r.node_id))
            for row in equal:
                plan.assignments[row.node_id] = target
                if len(facts) > 1:
                    plan.unresolved[row.node_id] = "different_extraction_facts_for_same_title"
            if len(equal) > 1:
                # Preserve a keyed node when available; never choose by presumed age.
                ordered = sorted(equal, key=lambda r: (not bool(r.existing_key), r.node_id))
                plan.merges.append(MergeGroup(target, ordered[0].node_id,
                                               [r.node_id for r in ordered[1:]]))

    # Every repeated target must be covered by exactly one explicit merge group.
    groups = {m.key: {m.survivor_id, *m.loser_ids} for m in plan.merges}
    targets: dict[str, set[int]] = {}
    for node_id, target in plan.assignments.items():
        targets.setdefault(target, set()).add(node_id)
    for target, ids in targets.items():
        if len(ids) > 1 and groups.get(target) != ids:
            raise ValueError(f"Unresolved existing key collision: {target}")
    return plan


_FETCH = """
MATCH (ev:Event) WHERE NOT ev:GDELTEvent
OPTIONAL MATCH (d:Document)-[:DESCRIBES]->(ev)
RETURN id(ev) AS node_id, elementId(ev) AS element_id, labels(ev) AS labels,
       properties(ev) AS properties, apoc.convert.toJson(properties(ev)) AS properties_json,
       ev.title AS title, ev.event_key AS existing_key,
       coalesce(ev.codebook_type, 'other.unclassified') AS codebook_type,
       d.url AS doc_url, coalesce(d.title, '') AS doc_title
"""
_PREFLIGHT_DUP_KEYS = """
MATCH (ev:Event)
WITH ev.event_key AS k, count(*) AS c
WHERE k IS NOT NULL AND c > 1
RETURN k AS event_key, c AS count ORDER BY c DESC
"""
_MISSING_KEYS = """
MATCH (ev:Event) WHERE NOT ev:GDELTEvent AND (ev.event_key IS NULL OR ev.event_key = '')
RETURN count(ev) AS missing
"""
_RELATIONSHIPS = """
MATCH (a)-[r]->(b)
WHERE (a:Event AND NOT a:GDELTEvent) OR (b:Event AND NOT b:GDELTEvent)
RETURN elementId(r) AS id, elementId(a) AS start, elementId(b) AS end,
       type(r) AS type, properties(r) AS properties
"""
_MERGE = """
UNWIND $groups AS row
CALL (row) {
  UNWIND range(0, size(row.ids)-1) AS i
  OPTIONAL MATCH (n:Event) WHERE elementId(n) = row.ids[i]
  WITH row, i, n ORDER BY i
  WITH row, collect(n) AS nodes
  CALL apoc.util.validate(size(nodes) <> size(row.ids), 'Missing merge node', [])
  CALL apoc.util.validate(
    any(i IN range(0,size(nodes)-1) WHERE
      apoc.convert.fromJsonMap(apoc.convert.toJson(properties(nodes[i])))
      <> apoc.convert.fromJsonMap(row.expected_json[i])),
    'Stale merge properties', [])
  CALL apoc.refactor.mergeNodes(nodes,
    {properties:'discard', mergeRels:false, produceSelfRel:true, preserveExistingSelfRels:true})
  YIELD node
  SET node.event_key = row.key, node.repair_merged_nodes_json = row.archive
  SET node += row.markers
  RETURN node
}
RETURN count(node) AS applied
"""
_SET_KEYS = """
UNWIND $rows AS row
OPTIONAL MATCH (ev:Event) WHERE elementId(ev) = row.id
CALL apoc.util.validate(ev IS NULL OR
  apoc.convert.fromJsonMap(apoc.convert.toJson(properties(ev)))
    <> apoc.convert.fromJsonMap(row.expected_json), 'Stale key node', [])
SET ev.event_key = row.key
SET ev += row.markers
RETURN count(ev) AS applied
"""


async def _fetch_rows(driver: Any) -> list[EventRow]:
    async with driver.session() as session:
        result = await session.run(_FETCH)
        return [EventRow(r['node_id'], r['title'] or '', r['codebook_type'],
                         r['doc_url'], r['doc_title'], r['existing_key'],
                         dict(r['properties']), r['element_id'], tuple(r['labels']),
                         r['properties_json'])
                async for r in result]


async def _archive(driver: Any, rows: list[EventRow], plan: BackfillPlan, path: Path) -> None:
    # Exclusive creation prevents overwriting the only pre-migration evidence.
    with path.open('x') as archive:
        archive.write(_json({'kind': 'plan', 'plan': asdict(plan)}) + '\n')
        for row in rows:
            archive.write(_json({'kind': 'node', **asdict(row)}) + '\n')
        async with driver.session() as session:
            result = await session.run(_RELATIONSHIPS)
            async for record in result:
                archive.write(_json({'kind': 'relationship', **record.data()}) + '\n')
        archive.flush()
        os.fsync(archive.fileno())


def _markers(plan: BackfillPlan, node_id: int) -> dict[str, str]:
    reason = plan.unresolved.get(node_id)
    if reason:
        return {'repair_identity_status': 'unresolved', 'repair_identity_reason': reason}
    return {}


async def run(driver: Any, *, dry_run: bool, archive_path: Path | None = None) -> BackfillPlan:
    rows = await _fetch_rows(driver)
    plan = plan_backfill(rows)
    log.info('backfill_event_key_plan', total=plan.total, groups=plan.group_count,
             duplicates=plan.duplicate_count, unresolved=len(plan.unresolved), dry_run=dry_run)
    if dry_run:
        return plan
    if archive_path is None:
        raise ValueError('--archive is required when applying')
    await _archive(driver, rows, plan, archive_path)
    by_id = {row.node_id: row for row in rows}
    merged = set()
    async with driver.session() as session:
        for group in plan.merges:
            ids = [group.survivor_id, *group.loser_ids]
            nodes = [by_id[i] for i in ids]
            payload = {'ids': [r.element_id for r in nodes], 'key': group.key,
                       'expected_json': [r.properties_json for r in nodes],
                       'archive': _json([asdict(r) for r in nodes]),
                       'markers': _markers(plan, group.survivor_id)}
            result = await session.run(_MERGE, groups=[payload])
            record = await result.single(strict=True)
            await result.consume()
            if record['applied'] != 1:
                raise RuntimeError('Merge did not apply')
            merged.update(ids)
        pending = [{'id': row.element_id, 'expected_json': row.properties_json,
                    'key': plan.key_for(row.node_id), 'markers': _markers(plan, row.node_id)}
                   for row in by_id.values() if row.node_id not in merged
                   and (row.existing_key != plan.key_for(row.node_id)
                        or any(row.properties.get(k) != v
                               for k, v in _markers(plan, row.node_id).items()))]
        for offset in range(0, len(pending), 500):
            batch = pending[offset:offset + 500]
            result = await session.run(_SET_KEYS, rows=batch)
            record = await result.single(strict=True)
            await result.consume()
            if record['applied'] != len(batch):
                raise RuntimeError('Key batch did not apply completely')
    await verify_complete(driver)
    return plan


async def verify_no_duplicate_keys(driver: Any) -> list[tuple[str, int]]:
    async with driver.session() as session:
        result = await session.run(_PREFLIGHT_DUP_KEYS)
        return [(r['event_key'], r['count']) async for r in result]


async def verify_complete(driver: Any) -> None:
    duplicates = await verify_no_duplicate_keys(driver)
    async with driver.session() as session:
        result = await session.run(_MISSING_KEYS)
        row = await result.single(strict=True)
    if duplicates or row['missing']:
        raise RuntimeError(f"Incomplete repair: {len(duplicates)} duplicate keys, "
                           f"{row['missing']} missing keys")
    log.info('backfill_event_key_verified', duplicate_keys=0, missing_keys=0)


def _build_driver() -> Any:
    import neo4j

    from config import settings
    return neo4j.AsyncGraphDatabase.driver(
        settings.neo4j_url, auth=(settings.neo4j_user, settings.neo4j_password),
        notifications_min_severity='OFF')


async def _main(dry_run: bool, archive_path: Path | None = None) -> None:
    driver = _build_driver()
    try:
        await run(driver, dry_run=dry_run, archive_path=archive_path)
    finally:
        await driver.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--archive', type=Path)
    args = parser.parse_args()
    asyncio.run(_main(dry_run=not args.apply, archive_path=args.archive))
