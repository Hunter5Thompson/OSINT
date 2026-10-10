"""Opt-in A08 database gate; never use the application database defaults.

Requires a disposable instance with the explicit HN marker and existing
Incident/Location uniqueness constraints. Collection alone is not a DB proof.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from neo4j import AsyncGraphDatabase

from app.cypher.incident_write import INCIDENT_CREATE_IDEMPOTENT, INCIDENT_UPSERT
from app.models.incident import Incident, IncidentStatus

_MARKER = "hn-b07-isolated-20261010"


@pytest.fixture
async def database():
    uri = os.environ.get("HN_TEST_NEO4J_URI")
    password = os.environ.get("HN_TEST_NEO4J_PASSWORD")
    if not uri or not password:
        pytest.fail("Explicit isolated HN Neo4j credentials are required")
    driver = AsyncGraphDatabase.driver(uri, auth=("neo4j", password))
    try:
        await driver.verify_connectivity()
        async with driver.session() as session:
            result = await session.run(
                "MATCH (:HNTestInstance {id: $marker}) RETURN true AS isolated",
                marker=_MARKER,
            )
            if await result.single() is None:
                pytest.fail("A08 isolated database marker is missing")
            result = await session.run("SHOW CONSTRAINTS YIELD labelsOrTypes, properties, type")
            constraints = await result.data()
            for label, key in (("Incident", "id"), ("Location", "loc_key")):
                assert any(
                    row["labelsOrTypes"] == [label]
                    and row["properties"] == [key]
                    and "UNIQUENESS" in row["type"]
                    for row in constraints
                ), f"Missing {label}.{key} uniqueness constraint"
        yield driver
    finally:
        await driver.close()


@pytest.fixture
async def case(database, monkeypatch):
    monkeypatch.setenv("NEO4J_PASSWORD", "test-settings-only")
    from app.services.incident_store import _upsert_params

    token = uuid4().hex
    record = Incident(
        id=f"hn-b07-{token}",
        kind="manual",
        title="original",
        severity="low",
        coords=(-0.0001, 20),
        location=f"HN B07 {token}",
        status=IncidentStatus.OPEN,
        trigger_ts=datetime(2026, 10, 10, tzinfo=UTC),
        sources=[],
        layer_hints=[],
        timeline=[],
    )
    params = _upsert_params(record, 1)
    params["create_nonce"] = token
    try:
        yield database, params
    finally:
        async with database.session() as session:
            await session.run(
                "MATCH (i:Incident) WHERE i.id IN $ids DETACH DELETE i",
                ids=[record.id, f"{record.id}-second"],
            )
            await session.run(
                "MATCH (l:Location) WHERE l.loc_key IN $keys DETACH DELETE l",
                keys=params["loc_key_candidates"],
            )


async def _run(driver, query, params):
    async with driver.session() as session:
        result = await session.run(query, params)
        return await result.data()


async def _seed(driver, keys):
    await _run(driver, "UNWIND $keys AS key CREATE (:Location {loc_key: key})", {"keys": keys})


async def _locations(driver, params):
    return await _run(
        driver,
        "MATCH (i:Incident {id: $incident_id})-[:OCCURRED_AT]->(l:Location) "
        "RETURN l.loc_key AS key, l.lat AS lat",
        params,
    )


@pytest.mark.parametrize(
    "query", [INCIDENT_UPSERT, INCIDENT_CREATE_IDEMPOTENT], ids=["upsert", "create_retry"]
)
async def test_new_location_uses_canonical_key_and_preserves_raw_position(case, query):
    driver, params = case
    assert len(await _run(driver, query, params)) == 1
    assert await _locations(driver, params) == [{"key": params["loc_key"], "lat": -0.0001}]


@pytest.mark.parametrize(
    "query", [INCIDENT_UPSERT, INCIDENT_CREATE_IDEMPOTENT], ids=["upsert", "create_retry"]
)
async def test_single_legacy_location_is_reused_without_rekey(case, query):
    driver, params = case
    legacy = params["loc_key_candidates"][1]
    await _seed(driver, [legacy])
    assert len(await _run(driver, query, params)) == 1
    assert await _locations(driver, params) == [{"key": legacy, "lat": None}]
    rows = await _run(
        driver,
        "MATCH (l:Location) WHERE l.loc_key IN $loc_key_candidates RETURN l.loc_key AS key",
        params,
    )
    assert rows == [{"key": legacy}]


@pytest.mark.parametrize(
    "query", [INCIDENT_UPSERT, INCIDENT_CREATE_IDEMPOTENT], ids=["upsert", "create_retry"]
)
async def test_multiple_aliases_reject_before_creating_incident(case, query):
    driver, params = case
    await _seed(driver, params["loc_key_candidates"])
    assert await _run(driver, query, params) == []
    assert (
        await _run(
            driver,
            "MATCH (i:Incident {id: $incident_id}) RETURN i.id AS id",
            params,
        )
        == []
    )


async def test_promoter_replay_keeps_terminal_state_even_with_alias_conflict(case):
    driver, params = case
    await _run(driver, INCIDENT_CREATE_IDEMPOTENT, params)
    await _seed(driver, [params["loc_key_candidates"][1]])
    await _run(
        driver,
        "MATCH (i:Incident {id: $incident_id}) SET i.status = 'closed', i.title = 'terminal'",
        params,
    )
    params["create_nonce"] = uuid4().hex
    params["title"] = "retry overwrite"
    rows = await _run(driver, INCIDENT_CREATE_IDEMPOTENT, params)
    assert len(rows) == 1
    assert rows[0]["status"] == "closed" and rows[0]["title"] == "terminal"
    assert await _locations(driver, params) == [{"key": params["loc_key"], "lat": -0.0001}]


@pytest.mark.parametrize(
    "query", [INCIDENT_UPSERT, INCIDENT_CREATE_IDEMPOTENT], ids=["upsert", "create_retry"]
)
async def test_exact_null_island_creates_no_location(case, query):
    driver, params = case
    params.update(lat=0.0, lon=0.0)
    assert len(await _run(driver, query, params)) == 1
    assert await _locations(driver, params) == []


async def test_upsert_conflict_preserves_existing_incident(case):
    driver, params = case
    await _run(driver, INCIDENT_UPSERT, params)
    await _seed(driver, [params["loc_key_candidates"][1]])
    params["title"] = "must not overwrite"
    assert await _run(driver, INCIDENT_UPSERT, params) == []
    rows = await _run(
        driver,
        "MATCH (i:Incident {id: $incident_id}) RETURN i.title AS title",
        params,
    )
    assert rows == [{"title": "original"}]


@pytest.mark.parametrize(
    "query", [INCIDENT_UPSERT, INCIDENT_CREATE_IDEMPOTENT], ids=["upsert", "create_retry"]
)
async def test_new_writers_share_one_canonical_location_under_concurrency(case, query):
    driver, params = case
    second = {
        **params,
        "incident_id": f"{params['incident_id']}-second",
        "create_nonce": uuid4().hex,
    }
    results = await asyncio.gather(_run(driver, query, params), _run(driver, query, second))
    assert all(len(rows) == 1 for rows in results)
    locations = await _run(
        driver,
        "MATCH (l:Location) WHERE l.loc_key IN $loc_key_candidates RETURN l.loc_key AS key",
        params,
    )
    assert locations == [{"key": params["loc_key"]}]
