"""Opt-in real Neo4j proofs for GET /graph/events/geo (HN-D03).

Runs the production Cypher against the isolated, marker-guarded test instance;
never against the application default URI.
"""
from __future__ import annotations

import os

import pytest
from neo4j import AsyncGraphDatabase

os.environ.setdefault("NEO4J_PASSWORD", "hn-b04-unused-default-client-password")

from app.routers import graph as graph_router  # noqa: E402

_MARKER_ID = "hn-i04-isolated-20260927"
_RECENT = 2_000_000_000
_OLD = 1_000_000_000


@pytest.fixture
async def driver():
    uri = os.environ.get("HN_TEST_NEO4J_URI")
    password = os.environ.get("HN_TEST_NEO4J_PASSWORD")
    if not uri or not password:
        pytest.fail("HN_TEST_NEO4J_URI and HN_TEST_NEO4J_PASSWORD are required")
    drv = AsyncGraphDatabase.driver(uri, auth=("neo4j", password))
    await drv.verify_connectivity()
    async with drv.session() as session:
        result = await session.run(
            "MATCH (m:HNTestInstance {id: $marker}) RETURN m.id AS id",
            marker=_MARKER_ID,
        )
        if await result.single() is None:
            await drv.close()
            pytest.fail(f"Neo4j test marker {_MARKER_ID!r} is missing")
        await session.run(
            "MATCH (n) WHERE NOT n:HNTestInstance DETACH DELETE n"
        )
    yield drv
    async with drv.session() as session:
        await session.run("MATCH (n) WHERE NOT n:HNTestInstance DETACH DELETE n")
    await drv.close()


@pytest.fixture(autouse=True)
def _route_reads_to_test_db(monkeypatch, driver):
    async def read(cypher, params):
        async with driver.session() as session:
            result = await session.run(cypher, params)
            return [dict(r) async for r in result]

    monkeypatch.setattr(graph_router, "_read_query", read)


async def _seed(driver, cypher: str, **params) -> None:
    async with driver.session() as session:
        await session.run(cypher, params)


async def _seed_event(driver, title, ctype, ts, *, loc=None, entity=None) -> None:
    await _seed(
        driver,
        "CREATE (ev:Event {title: $title, codebook_type: $ctype, severity: 'low', "
        "timestamp: $ts}) "
        "WITH ev "
        "FOREACH (_ IN CASE WHEN $loc IS NULL THEN [] ELSE [1] END | "
        "  CREATE (ev)-[:OCCURRED_AT]->(:Location {name: $title + '-loc'}) ) "
        "WITH ev "
        "FOREACH (_ IN CASE WHEN $entity IS NULL THEN [] ELSE [1] END | "
        "  MERGE (e:Entity {name: $entity}) CREATE (ev)-[:INVOLVES]->(e) )",
        title=title, ctype=ctype, ts=ts, loc=loc, entity=entity,
    )
    if loc:
        await _seed(
            driver,
            "MATCH (l:Location {name: $name}) SET l += $props",
            name=f"{title}-loc", props=loc,
        )


@pytest.mark.asyncio
async def test_codebook_filter_binds_to_event_not_to_optional_location(driver):
    """Newer non-military rows must not crowd out the older matching event."""
    for i in range(4):
        await _seed_event(
            driver, f"civil-{i}", "other.misc", _RECENT + i, loc={"lat": 1.0, "lon": 2.0}
        )
    await _seed_event(driver, "old-mil", "military.strike", _OLD, loc={"lat": 3.0, "lon": 4.0})

    resp = await graph_router.get_geo_events(
        entity=None, codebook_type="military", limit=3
    )

    assert [e.title for e in resp.events] == ["old-mil"]
    assert resp.total_count == 1


@pytest.mark.asyncio
async def test_codebook_filter_keeps_matching_event_without_location(driver):
    await _seed_event(driver, "mil-noloc", "military.strike", _RECENT)
    await _seed_event(driver, "civil", "other.misc", _RECENT + 1)

    resp = await graph_router.get_geo_events(
        entity=None, codebook_type="military", limit=10
    )

    assert [e.title for e in resp.events] == ["mil-noloc"]
    assert resp.events[0].lat is None and resp.events[0].lon is None


@pytest.mark.asyncio
async def test_entity_and_codebook_filters_combine(driver):
    for i in range(4):
        await _seed_event(
            driver, f"civil-{i}", "other.misc", _RECENT + i,
            loc={"lat": 1.0, "lon": 2.0}, entity="NATO",
        )
    await _seed_event(
        driver, "nato-mil", "military.exercise", _OLD,
        loc={"lat": 5.0, "lon": 6.0}, entity="NATO",
    )
    await _seed_event(
        driver, "other-mil", "military.strike", _RECENT + 10,
        loc={"lat": 7.0, "lon": 8.0}, entity="Other",
    )

    resp = await graph_router.get_geo_events(
        entity="NATO", codebook_type="military", limit=3
    )

    assert [e.title for e in resp.events] == ["nato-mil"]


@pytest.mark.asyncio
async def test_unfiltered_event_without_location_is_still_returned(driver):
    """Semantics stay 'event with optional location', not an inner join."""
    await _seed_event(driver, "noloc", "other.misc", _RECENT)

    resp = await graph_router.get_geo_events(entity=None, codebook_type=None, limit=10)

    assert [e.title for e in resp.events] == ["noloc"]
    assert resp.events[0].lat is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "loc",
    [
        {"lat": "abc", "lon": 10.0},
        {"lat": 95.0, "lon": 10.0},
        {"lat": 10.0, "lon": 181.0},
        {"lat": float("nan"), "lon": 10.0},
        {"lat": float("inf"), "lon": 10.0},
        {"lat": 10.0},
        {"lon": 10.0},
        {"lat": True, "lon": 10.0},
    ],
    ids=["str-lat", "lat-range", "lon-range", "nan", "inf", "no-lon", "no-lat", "bool-lat"],
)
async def test_broken_coordinate_pair_yields_event_without_geometry(driver, loc):
    await _seed_event(driver, "broken", "other.misc", _RECENT, loc=loc)

    resp = await graph_router.get_geo_events(entity=None, codebook_type=None, limit=10)

    assert [e.title for e in resp.events] == ["broken"]
    ev = resp.events[0]
    assert ev.lat is None and ev.lon is None
    assert ev.location_name == "broken-loc"


@pytest.mark.asyncio
async def test_true_zero_coordinates_are_preserved(driver):
    await _seed_event(driver, "zero", "other.misc", _RECENT, loc={"lat": 0.0, "lon": 0.0})
    await _seed_event(driver, "int-zero", "other.misc", _RECENT - 1, loc={"lat": 0, "lon": -180})

    resp = await graph_router.get_geo_events(entity=None, codebook_type=None, limit=10)

    by_title = {e.title: e for e in resp.events}
    assert (by_title["zero"].lat, by_title["zero"].lon) == (0.0, 0.0)
    assert (by_title["int-zero"].lat, by_title["int-zero"].lon) == (0.0, -180.0)


@pytest.mark.asyncio
async def test_limit_is_still_applied_and_bound(driver):
    for i in range(5):
        await _seed_event(driver, f"e{i}", "other.misc", _RECENT + i, loc={"lat": 1, "lon": 1})

    resp = await graph_router.get_geo_events(entity=None, codebook_type=None, limit=2)

    assert [e.title for e in resp.events] == ["e4", "e3"]
