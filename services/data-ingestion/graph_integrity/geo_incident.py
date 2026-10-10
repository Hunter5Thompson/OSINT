"""Backfill: wire existing Incidents to :Location via OCCURRED_AT (idempotent)."""

from __future__ import annotations

from typing import Any

from graph_integrity.loc_key import incident_key, incident_key_candidates
from graph_integrity.neo4j_client import Neo4jClient

SELECT_UNWIRED_INCIDENTS = """
MATCH (i:Incident)
WHERE i.lat IS NOT NULL AND i.lon IS NOT NULL
  AND NOT (i.lat = 0.0 AND i.lon = 0.0)
  AND NOT (i)-[:OCCURRED_AT]->(:Location)
RETURN i.id AS id, i.location AS location, i.lat AS lat, i.lon AS lon
"""

WIRE_INCIDENT_LOCATION = """
MATCH (i:Incident {id: $incident_id})
OPTIONAL MATCH (existing_location:Location)
WHERE existing_location.loc_key IN $loc_key_candidates
WITH i, collect(existing_location.loc_key) AS existing_loc_keys
WHERE size(existing_loc_keys) <= 1
MERGE (l:Location {loc_key: coalesce(head(existing_loc_keys), $loc_key)})
  ON CREATE SET l.lat = $lat, l.lon = $lon, l.name = $location,
                l.geo_basis = 'incident_report'
MERGE (i)-[:OCCURRED_AT]->(l)
RETURN l.loc_key AS loc_key
"""


def build_wire_params(row: dict[str, Any]) -> dict[str, Any] | None:
    if row["lat"] == 0.0 and row["lon"] == 0.0:  # null-island sentinel -> no Location
        return None
    return {
        "incident_id": row["id"],
        "loc_key": incident_key(row.get("location"), row["lat"], row["lon"]),
        "loc_key_candidates": list(
            incident_key_candidates(row.get("location"), row["lat"], row["lon"])
        ),
        "lat": row["lat"],
        "lon": row["lon"],
        "location": row.get("location"),
    }


async def run(client: Neo4jClient, dry_run: bool = False) -> int:
    rows = await client.run(SELECT_UNWIRED_INCIDENTS)
    if dry_run:
        return len(rows)
    wired = 0
    for row in rows:
        params = build_wire_params(row)
        if params is None:
            continue
        result = await client.run(WIRE_INCIDENT_LOCATION, params)
        if not result:
            raise ValueError(f"incident location write rejected: {row['id']}")
        wired += 1
    return wired
