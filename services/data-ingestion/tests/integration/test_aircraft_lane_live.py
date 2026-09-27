"""Exercise the batch selector in Neo4j using in-memory maps, with no writes."""

import pytest

from config import Settings
from graph_integrity.neo4j_client import Neo4jClient
from graph_integrity.spatial_batch import COUNT_UNSTABLE_LOCATION_RECORDS


@pytest.mark.live
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "location,expected",
    [
        ({"type": "geopolitical_hotspot", "name": "ukraine"}, 0),
        ({"type": "geopolitical_hotspot", "lat": 48.0, "lon": 37.8}, 1),
        ({"type": "geopolitical_hotspot", "lat": 48.0}, 1),
        ({"type": "aircraft_observation"}, 1),
        ({"type": "aircraft_observation", "loc_key": "aircraft-observation:a"}, 0),
        ({"type": "unrelated", "lat": 48.0}, 0),
    ],
)
async def test_aircraft_cursor_gate_distinguishes_observations_from_theatres(
    location: dict[str, object], expected: int,
) -> None:
    settings = Settings()
    client = Neo4jClient(settings.neo4j_url, settings.neo4j_user, settings.neo4j_password)
    # Keep the production predicate and aggregation. WITH is required between
    # UNWIND and WHERE; the fixture never creates a Location or a relationship.
    query = COUNT_UNSTABLE_LOCATION_RECORDS["military_aircraft"].replace(
        "MATCH (l:Location)", "UNWIND $locations AS l WITH l"
    )
    try:
        assert await client.run(query, {"locations": [location]}) == [{"count": expected}]
    finally:
        await client.close()
