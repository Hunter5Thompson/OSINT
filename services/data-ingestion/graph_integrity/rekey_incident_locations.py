"""WP-07 repair: re-key collided incident :Location nodes onto coordinate-bearing
keys and clean the orphaned old nodes. Idempotent + dry-run-first.

Two distinct incidents that shared a location slug at different coordinates were
MERGEd onto ONE name-keyed :Location (the second silently inheriting the first's
coords). With the coordinate-bearing incident_key now live, this job rewires each
incident's OCCURRED_AT onto the correct coord-bearing Location and deletes the
orphaned 'incident:'-prefixed nodes left behind.

Operational order:
  1. run --dry-run               (review the rewire count)
  2. run (apply)                 (rewire + orphan cleanup; re-runnable)
  3. verify_no_duplicate_loc_keys(client) MUST return []
  4. apply migrations/location_loc_key_unique.cypher
"""
from __future__ import annotations

from dataclasses import dataclass, field

import structlog

from graph_integrity.loc_key import incident_key

log = structlog.get_logger(__name__)

FETCH_INCIDENT_LOCATIONS = """
MATCH (i:Incident)-[:OCCURRED_AT]->(l:Location)
WHERE l.loc_key STARTS WITH 'incident:'
RETURN i.id AS incident_id, i.location AS location,
       i.lat AS lat, i.lon AS lon, l.loc_key AS current_loc_key
"""

REWIRE = """
MATCH (i:Incident {id: $incident_id})
MERGE (l:Location {loc_key: $new_key})
  ON CREATE SET l.lat = $lat, l.lon = $lon, l.name = $location,
                l.geo_basis = 'incident_report'
MERGE (i)-[:OCCURRED_AT]->(l)
WITH i, l
MATCH (i)-[r:OCCURRED_AT]->(old:Location) WHERE old <> l
DELETE r
"""

CLEANUP_ORPHAN_INCIDENT_LOCATIONS = """
MATCH (l:Location)
WHERE l.loc_key STARTS WITH 'incident:' AND NOT ()-[:OCCURRED_AT]->(l)
DETACH DELETE l
RETURN count(l) AS deleted
"""

DUP_LOC_KEY_PREFLIGHT = """
MATCH (l:Location)
WITH l.loc_key AS key, count(*) AS c
WHERE key IS NOT NULL AND c > 1
RETURN key, c ORDER BY c DESC
"""


@dataclass
class IncidentLoc:
    incident_id: str
    location: str | None
    lat: float
    lon: float
    current_loc_key: str

    def desired_loc_key(self) -> str:
        return incident_key(self.location, self.lat, self.lon)


@dataclass
class RekeyPlan:
    rewires: list[tuple[str, str, str]] = field(default_factory=list)  # (id, old, new)

    @property
    def rewire_count(self) -> int:
        return len(self.rewires)


def plan_rekey(rows: list[IncidentLoc]) -> RekeyPlan:
    """Pure: which incidents need their Location re-keyed (current != desired)."""
    plan = RekeyPlan()
    for r in rows:
        if r.lat == 0.0 and r.lon == 0.0:
            continue
        new = r.desired_loc_key()
        if new != r.current_loc_key:
            plan.rewires.append((r.incident_id, r.current_loc_key, new))
    return plan


async def _fetch_rows(client) -> list[IncidentLoc]:
    raw = await client.run(FETCH_INCIDENT_LOCATIONS)
    return [
        IncidentLoc(
            incident_id=row["incident_id"], location=row.get("location"),
            lat=row["lat"], lon=row["lon"], current_loc_key=row["current_loc_key"],
        )
        for row in raw
    ]


async def run(client, *, dry_run: bool = False) -> int:
    """Re-key collided incident Locations. Returns the rewire count."""
    rows = await _fetch_rows(client)
    plan = plan_rekey(rows)
    by_id = {r.incident_id: r for r in rows}
    log.info("rekey_incident_locations_plan", rewires=plan.rewire_count, dry_run=dry_run)
    if dry_run:
        return plan.rewire_count
    for incident_id, _old_key, new_key in plan.rewires:
        r = by_id[incident_id]
        await client.run(REWIRE, {
            "incident_id": incident_id, "new_key": new_key,
            "lat": r.lat, "lon": r.lon, "location": r.location,
        })
    result = await client.run(CLEANUP_ORPHAN_INCIDENT_LOCATIONS)
    orphans_deleted = int(result[0]["deleted"]) if result else 0
    log.info("rekey_incident_locations_done",
             rewires=plan.rewire_count, orphans_deleted=orphans_deleted)
    return plan.rewire_count


async def verify_no_duplicate_loc_keys(client) -> list[tuple[str, int]]:
    """Preflight before applying location_loc_key_unique.cypher -- MUST return []."""
    rows = await client.run(DUP_LOC_KEY_PREFLIGHT)
    return [(row["key"], row["c"]) for row in rows]
