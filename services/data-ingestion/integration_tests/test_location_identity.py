"""Prepared A08 backfill gate against an explicitly isolated Neo4j instance."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from neo4j import AsyncGraphDatabase

from graph_integrity.geo_incident import WIRE_INCIDENT_LOCATION, build_wire_params


@pytest.fixture
async def case():
    uri = os.environ.get("HN_TEST_NEO4J_URI")
    password = os.environ.get("HN_TEST_NEO4J_PASSWORD")
    if not uri or not password:
        pytest.fail("Explicit isolated HN Neo4j credentials are required")
    driver = AsyncGraphDatabase.driver(uri, auth=("neo4j", password))
    token = uuid4().hex
    params = build_wire_params(
        {"id": f"hn-b07-{token}", "location": f"HN B07 {token}", "lat": -0.0001, "lon": 20.0}
    )
    assert params is not None
    verified = False
    try:
        await driver.verify_connectivity()
        async with driver.session() as session:
            result = await session.run(
                "MATCH (:HNTestInstance {id: $marker}) RETURN true AS isolated",
                marker="hn-b07-isolated-20261010",
            )
            if await result.single() is None:
                pytest.fail("A08 isolated database marker is missing")
            verified = True
            await session.run("CREATE (:Incident {id: $id})", id=params["incident_id"])
        yield driver, params
    finally:
        if verified:
            async with driver.session() as session:
                await session.run(
                    "MATCH (i:Incident {id: $id}) DETACH DELETE i",
                    id=params["incident_id"],
                )
                await session.run(
                    "MATCH (l:Location) WHERE l.loc_key IN $keys DETACH DELETE l",
                    keys=params["loc_key_candidates"],
                )
        await driver.close()


async def _run(driver, query, params):
    async with driver.session() as session:
        result = await session.run(query, params)
        return await result.data()


@pytest.mark.parametrize("existing", ["none", "legacy", "conflict"])
async def test_backfill_resolves_aliases_before_wiring_and_is_idempotent(case, existing):
    driver, params = case
    keys = params["loc_key_candidates"]
    seed = [] if existing == "none" else [keys[1]] if existing == "legacy" else keys
    await _run(
        driver,
        "UNWIND $keys AS key CREATE (:Location {loc_key: key})",
        {"keys": seed},
    )
    rows = await _run(driver, WIRE_INCIDENT_LOCATION, params)
    expected = [] if existing == "conflict" else [{"loc_key": keys[1] if seed else keys[0]}]
    assert rows == expected
    assert await _run(driver, WIRE_INCIDENT_LOCATION, params) == expected
    edges = await _run(
        driver,
        "MATCH (:Incident {id: $incident_id})-[r:OCCURRED_AT]->(:Location) "
        "RETURN count(r) AS count",
        params,
    )
    assert edges == [{"count": 0 if existing == "conflict" else 1}]
