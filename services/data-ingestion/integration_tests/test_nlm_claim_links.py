"""Opt-in real Neo4j proof for typed NLM claim->entity links (HN-A04).

Runs the production statements against the isolated, marker-guarded test
instance; never against the application default URI.
"""
from __future__ import annotations

import os

import pytest
from neo4j import AsyncGraphDatabase

from nlm_ingest.ingest_neo4j import _build_statements
from nlm_ingest.schemas import Claim, Entity, Extraction

_MARKER_ID = "hn-i04-isolated-20260927"


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
        await session.run("MATCH (n) WHERE NOT n:HNTestInstance DETACH DELETE n")
    yield drv
    async with drv.session() as session:
        await session.run("MATCH (n) WHERE NOT n:HNTestInstance DETACH DELETE n")
    await drv.close()


def _extraction(entities: list[Entity], involved: list[str]) -> Extraction:
    return Extraction(
        notebook_id="nb-a04",
        entities=entities,
        relations=[],
        claims=[
            Claim(
                statement="Mercury was mentioned",
                type="factual",
                polarity="neutral",
                entities_involved=involved,
                confidence=0.9,
                temporal_scope="ongoing",
            )
        ],
        extraction_model="test",
        prompt_version="v3",
        source_kind="report",
        source_id="report-1",
    )


async def _write(driver, extraction: Extraction) -> None:
    async with driver.session() as session:
        for stmt in _build_statements(extraction, "RAND", []):
            await session.run(stmt["statement"], stmt["parameters"])


async def _involves(driver) -> list[dict]:
    async with driver.session() as session:
        result = await session.run(
            "MATCH (:Claim)-[:INVOLVES]->(e:Entity) "
            "RETURN e.name AS name, e.type AS type ORDER BY e.type"
        )
        return [dict(r) async for r in result]


async def _seed_homonyms(driver) -> None:
    async with driver.session() as session:
        await session.run(
            "CREATE (:Entity {name: 'Mercury', type: 'WEAPON_SYSTEM'}), "
            "(:Entity {name: 'Mercury', type: 'ORGANIZATION'})"
        )


@pytest.mark.asyncio
async def test_homonym_entity_gets_exactly_one_typed_edge(driver):
    await _seed_homonyms(driver)
    ex = _extraction(
        [Entity(name="Mercury", type="ORGANIZATION", aliases=[], confidence=0.9)],
        ["Mercury"],
    )

    await _write(driver, ex)

    assert await _involves(driver) == [{"name": "Mercury", "type": "ORGANIZATION"}]


@pytest.mark.asyncio
async def test_untyped_claim_entity_is_not_linked_by_name_only(driver):
    await _seed_homonyms(driver)
    ex = _extraction(
        [Entity(name="Other", type="ORGANIZATION", aliases=[], confidence=0.9)],
        ["Mercury"],
    )

    await _write(driver, ex)

    assert await _involves(driver) == []


@pytest.mark.asyncio
async def test_ambiguous_types_in_one_extraction_are_not_guessed(driver):
    await _seed_homonyms(driver)
    ex = _extraction(
        [
            Entity(name="Mercury", type="ORGANIZATION", aliases=[], confidence=0.9),
            Entity(name="Mercury", type="WEAPON_SYSTEM", aliases=[], confidence=0.9),
        ],
        ["Mercury"],
    )

    await _write(driver, ex)

    assert await _involves(driver) == []


@pytest.mark.asyncio
async def test_canonical_alias_links_to_canonical_name_and_type(driver):
    ex = _extraction(
        [Entity(name="US Navy", type="ORGANIZATION", aliases=[], confidence=0.9)],
        ["US Navy"],
    )

    await _write(driver, ex)

    assert await _involves(driver) == [{"name": "U.S. Navy", "type": "MILITARY_UNIT"}]


@pytest.mark.asyncio
async def test_preexisting_name_only_edges_are_left_untouched(driver):
    """A04 must not remove legacy edges; that cleanup belongs to R01."""
    await _seed_homonyms(driver)
    async with driver.session() as session:
        await session.run(
            "CREATE (c:Claim {statement_hash: 'legacy'}) "
            "WITH c MATCH (e:Entity {name: 'Mercury'}) CREATE (c)-[:INVOLVES]->(e)"
        )
    ex = _extraction(
        [Entity(name="Mercury", type="ORGANIZATION", aliases=[], confidence=0.9)],
        ["Mercury"],
    )

    await _write(driver, ex)

    assert await _involves(driver) == [
        {"name": "Mercury", "type": "ORGANIZATION"},
        {"name": "Mercury", "type": "ORGANIZATION"},
        {"name": "Mercury", "type": "WEAPON_SYSTEM"},
    ]
