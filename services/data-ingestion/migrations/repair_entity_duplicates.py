"""Explicitly reviewed Entity merges; never infer identity from names alone.

Callers must supply an evidence-backed list of exact element IDs. All original
nodes and adjacent relationships are archived and fsynced before mutation.
Relationship properties and multiplicity survive unchanged. Conflicting scalar
values remain available in repair_merged_nodes_json on the surviving Entity.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from migrations.backfill_event_key import _json


def validate_group(properties: list[dict[str, Any]]) -> None:
    identities = {(p.get('name'), p.get('type')) for p in properties}
    if len(properties) < 2 or len(identities) != 1 or any(None in i for i in identities):
        raise ValueError('Entity identity differs or group is incomplete')


def merged_properties(properties: list[dict[str, Any]]) -> dict[str, Any]:
    validate_group(properties)
    result: dict[str, Any] = {}
    aliases = sorted({a for p in properties for a in p.get('aliases', [])})
    if aliases:
        result['aliases'] = aliases
    for key, choose in [('confidence', max), ('first_seen', min), ('last_seen', max)]:
        values = [p[key] for p in properties if p.get(key) is not None]
        if values:
            result[key] = choose(values)
    return result


_FETCH = """
UNWIND $ids AS eid
MATCH (e:Entity) WHERE elementId(e) = eid
RETURN elementId(e) AS id, properties(e) AS properties, labels(e) AS labels,
       apoc.convert.toJson(properties(e)) AS properties_json,
       COUNT { (e)--() } AS degree
"""
_EDGES = """
MATCH (a)-[r]->(b) WHERE elementId(a) IN $ids OR elementId(b) IN $ids
RETURN elementId(r) AS id, elementId(a) AS start, elementId(b) AS end,
       type(r) AS type, properties(r) AS properties
"""
_MERGE = """
UNWIND range(0,size($ids)-1) AS i
OPTIONAL MATCH (e:Entity) WHERE elementId(e) = $ids[i]
WITH i,e ORDER BY i
WITH collect(e) AS nodes
CALL apoc.util.validate(size(nodes) <> size($ids), 'Missing Entity', [])
CALL apoc.util.validate(
  any(i IN range(0,size(nodes)-1) WHERE
      apoc.convert.fromJsonMap(apoc.convert.toJson(properties(nodes[i])))
    <> apoc.convert.fromJsonMap($expected_json[i])),
  'Stale Entity properties', [])
CALL apoc.refactor.mergeNodes(nodes,
  {properties:'discard', mergeRels:false, produceSelfRel:true, preserveExistingSelfRels:true})
YIELD node
SET node += $properties
SET node.repair_merged_nodes_json = $archive
RETURN elementId(node) AS survivor
"""


async def run(driver: Any, groups: list[list[str]], *, archive_path: Path) -> dict[str, str]:
    flat = [eid for group in groups for eid in group]
    if len(flat) != len(set(flat)):
        raise ValueError('Overlapping Entity groups')
    prepared = []
    async with driver.session() as session:
        for group in groups:
            result = await session.run(_FETCH, ids=group)
            rows = [r.data() async for r in result]
            if len(rows) != len(group):
                raise ValueError('Missing reviewed Entity')
            rows.sort(key=lambda r: (-r['degree'], str(r['properties'].get('first_seen', '9999')),
                                     r['id']))
            properties = [r['properties'] for r in rows]
            prepared.append({'ids': [r['id'] for r in rows],
                             'expected_json': [r['properties_json'] for r in rows],
                             'properties': merged_properties(properties), 'archive': _json(rows)})
        with archive_path.open('x') as archive:
            archive.write(_json({'kind': 'groups', 'groups': prepared}) + '\n')
            result = await session.run(_EDGES, ids=flat)
            async for row in result:
                archive.write(_json({'kind': 'relationship', **row.data()}) + '\n')
            archive.flush()
            os.fsync(archive.fileno())
        mapping = {}
        for group in prepared:
            result = await session.run(_MERGE, **group)
            row = await result.single(strict=True)
            await result.consume()
            if row['survivor'] != group['ids'][0]:
                raise RuntimeError('Unexpected Entity survivor')
            mapping.update(dict.fromkeys(group['ids'], row['survivor']))
    return mapping
