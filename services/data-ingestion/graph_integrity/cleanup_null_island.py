"""WP-11 repair: detach and delete the shared (0,0) null-island :Location nodes.

Pre-fix writers MERGEd every (0,0)-with-no-ids event onto a single Location in
the Gulf of Guinea. With both writers now dropping (0,0), this job detaches the
events (they become honestly geoless) and deletes the (0,0) nodes. Idempotent:
a second run finds 0 null-island nodes and is a no-op.

Operational order: run --dry-run (review counts) -> run (apply).
"""
from __future__ import annotations

import structlog

log = structlog.get_logger(__name__)

COUNT_NULL_ISLAND = """
MATCH (l:Location) WHERE l.lat = 0.0 AND l.lon = 0.0
OPTIONAL MATCH (n)-[:OCCURRED_AT]->(l)
RETURN count(DISTINCT l) AS null_island_locations, count(n) AS attached_nodes
"""

DELETE_NULL_ISLAND = """
MATCH (l:Location) WHERE l.lat = 0.0 AND l.lon = 0.0
DETACH DELETE l
RETURN count(l) AS deleted
"""


async def run(client, *, dry_run: bool = False) -> int:
    """Delete (0,0) Locations. Returns the count of null-island nodes found/deleted."""
    counts = await client.run(COUNT_NULL_ISLAND)
    found = int(counts[0]["null_island_locations"]) if counts else 0
    attached = int(counts[0]["attached_nodes"]) if counts else 0
    log.info("cleanup_null_island_plan", null_island_locations=found,
             attached_nodes=attached, dry_run=dry_run)
    if dry_run:
        return found
    result = await client.run(DELETE_NULL_ISLAND)
    deleted = int(result[0]["deleted"]) if result else 0
    log.info("cleanup_null_island_done", deleted=deleted)
    return deleted
