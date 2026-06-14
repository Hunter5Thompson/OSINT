"""Backfill: wire existing Incidents to :Location via OCCURRED_AT (idempotent)."""
from __future__ import annotations

from typing import Any

from graph_integrity.loc_key import incident_key
from graph_integrity.neo4j_client import Neo4jClient

SELECT_UNWIRED_INCIDENTS = """
MATCH (i:Incident)
WHERE i.lat IS NOT NULL AND i.lon IS NOT NULL
  AND NOT (i)-[:OCCURRED_AT]->(:Location)
RETURN i.id AS id, i.location AS location, i.lat AS lat, i.lon AS lon
"""

WIRE_INCIDENT_LOCATION = """
MATCH (i:Incident {id: $incident_id})
MERGE (l:Location {loc_key: $loc_key})
  ON CREATE SET l.lat = $lat, l.lon = $lon, l.name = $location,
                l.geo_basis = 'incident_report'
MERGE (i)-[:OCCURRED_AT]->(l)
"""


def build_wire_params(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "incident_id": row["id"],
        "loc_key": incident_key(row.get("location"), row["lat"], row["lon"]),
        "lat": row["lat"], "lon": row["lon"], "location": row.get("location"),
    }


async def run(client: Neo4jClient, dry_run: bool = False) -> int:
    rows = await client.run(SELECT_UNWIRED_INCIDENTS)
    if dry_run:
        return len(rows)
    for row in rows:
        await client.run(WIRE_INCIDENT_LOCATION, build_wire_params(row))
    return len(rows)
