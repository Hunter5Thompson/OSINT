"""Opt-in real Neo4j race proofs; never run through the application default URI."""
from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import neo4j
import pytest
from neo4j import AsyncGraphDatabase

os.environ.setdefault("NEO4J_PASSWORD", "hn-i04-unused-default-client-password")

from app.cypher.incident_write import INCIDENT_MUTATION_LOCK  # noqa: E402
from app.models.incident import (  # noqa: E402
    IncidentCreateRequest,
    IncidentStatus,
    IncidentTimelineEvent,
)
from app.services import incident_store, neo4j_client  # noqa: E402

_MARKER_ID = "hn-i04-isolated-20260927"


async def _open_marked_driver():
    uri = os.environ.get("HN_TEST_NEO4J_URI")
    password = os.environ.get("HN_TEST_NEO4J_PASSWORD")
    if not uri or not password:
        pytest.fail("HN_TEST_NEO4J_URI and HN_TEST_NEO4J_PASSWORD are required")
    driver = AsyncGraphDatabase.driver(uri, auth=("neo4j", password))
    await driver.verify_connectivity()
    async with driver.session() as session:
        result = await session.run(
            "MATCH (m:HNTestInstance {id: $marker}) RETURN m.id AS id",
            marker=_MARKER_ID,
        )
        marker = await result.single()
    if marker is None:
        await driver.close()
        pytest.fail(f"Neo4j test marker {_MARKER_ID!r} is missing")
    return driver


def _install_controlled_writer(monkeypatch, driver, original_write_transaction):
    lock_acquired = asyncio.Event()
    release_first = asyncio.Event()
    second_started = asyncio.Event()
    tags: list[str] = []

    async def get_test_driver():
        return driver

    async def controlled_write_transaction(callback, *, metadata=None):
        tags.append(str((metadata or {}).get("incident_mutation_id")))
        if len(tags) == 2:
            second_started.set()

        async def controlled_callback(transaction):
            class TransactionProxy:
                async def run(self, query, params=None, **kwargs):
                    result = await transaction.run(query, params, **kwargs)
                    if query == INCIDENT_MUTATION_LOCK and len(tags) == 1:
                        lock_acquired.set()
                        await release_first.wait()
                    return result

            return await callback(TransactionProxy())

        return await original_write_transaction(
            controlled_callback, metadata=metadata
        )

    async def wait_until_second_blocked():
        async def is_blocked():
            if len(tags) < 2:
                return False
            async with driver.session() as session:
                result = await session.run(
                    "SHOW TRANSACTIONS YIELD status, metaData "
                    "WHERE metaData.incident_mutation_id = $tag RETURN status",
                    tag=tags[1],
                )
                rows = [dict(record) async for record in result]
            return any("Blocked by:" in str(row["status"]) for row in rows)

        async with asyncio.timeout(10):
            await second_started.wait()
            while not await is_blocked():
                pass

    monkeypatch.setattr(neo4j_client, "get_graph_client", get_test_driver)
    monkeypatch.setattr(incident_store, "write_transaction", controlled_write_transaction)
    return lock_acquired, release_first, wait_until_second_blocked


@pytest.mark.asyncio
async def test_concurrent_signal_updates_keep_both_events_after_lock_wait(monkeypatch):
    """The actual store callbacks serialize on the DB lock before reading the record."""
    driver = await _open_marked_driver()
    original_write_transaction = incident_store.write_transaction
    first: asyncio.Task | None = None
    second: asyncio.Task | None = None
    lock_acquired, release_first, wait_until_second_blocked = _install_controlled_writer(
        monkeypatch, driver, original_write_transaction
    )
    incident_id: str | None = None
    test_location = f"hn-i04-{uuid4().hex}"
    try:
        seeded = await incident_store.create_incident(
            IncidentCreateRequest(
                title="HN-I04 lock regression",
                kind="test.incident",
                severity="low",
                coords=(41.173, 29.284),
                location=test_location,
                sources=["hn-i04-test"],
                layer_hints=["hn-i04-test"],
            )
        )
        incident_id = seeded.id
        async with driver.session() as session:
            location_result = await session.run(
                "MATCH (i:Incident {id: $id})-[r:OCCURRED_AT]->(l:Location) "
                "SET l.spatial_catalog_revision = $sentinel, l.spatial_conflict = true "
                "RETURN elementId(r) AS relationship_id, elementId(l) AS element_id, "
                "l.loc_key AS loc_key, "
                "l.spatial_catalog_revision AS revision, l.spatial_conflict AS conflict",
                id=incident_id,
                sentinel="hn-i04-spatial-sentinel",
            )
            location_before = await location_result.single()
        assert location_before is not None
        first = asyncio.create_task(
            incident_store.apply_signal_update(
                incident_id,
                timeline_event=IncidentTimelineEvent(
                    t_offset_s=10.0, kind="signal", text="race-1"
                ),
                severity="high",
                sources_to_merge=["source-1"],
                layer_hints_to_merge=["hint-1"],
            )
        )
        await asyncio.wait_for(lock_acquired.wait(), timeout=10)
        second = asyncio.create_task(
            incident_store.apply_signal_update(
                incident_id,
                timeline_event=IncidentTimelineEvent(
                    t_offset_s=11.0, kind="signal", text="race-2"
                ),
                severity="elevated",
                sources_to_merge=["source-2"],
                layer_hints_to_merge=["hint-2"],
            )
        )

        await wait_until_second_blocked()
        release_first.set()
        first_result, second_result = await asyncio.gather(first, second)

        assert first_result.status == second_result.status == "applied"
        persisted = await incident_store.get_incident(incident_id)
        assert persisted is not None
        assert {event.text for event in persisted.timeline[1:]} == {"race-1", "race-2"}
        assert persisted.severity == "high"
        assert persisted.sources == ["hn-i04-test", "source-1", "source-2"]
        assert persisted.layer_hints == ["hn-i04-test", "hint-1", "hint-2"]
        assert persisted.coords == (41.173, 29.284)
        async with driver.session() as session:
            location_result = await session.run(
                "MATCH (i:Incident {id: $id})-[r:OCCURRED_AT]->(l:Location) "
                "RETURN elementId(r) AS relationship_id, elementId(l) AS element_id, "
                "l.loc_key AS loc_key, "
                "l.spatial_catalog_revision AS revision, l.spatial_conflict AS conflict",
                id=incident_id,
            )
            location_after = await location_result.single()
        assert location_after is not None
        assert dict(location_after) == dict(location_before)
    finally:
        release_first.set()
        running_tasks = [task for task in (first, second) if task is not None]
        if running_tasks:
            await asyncio.gather(*running_tasks, return_exceptions=True)
        if incident_id is not None:
            async with driver.session() as session:
                await session.run(
                    "MATCH (i:Incident {id: $id}) "
                    "OPTIONAL MATCH (i)-[:OCCURRED_AT]->(l:Location) "
                    "WITH i, collect(l) AS locations DETACH DELETE i "
                    "WITH locations UNWIND locations AS l "
                    "WITH l WHERE l.name = $location AND NOT (l)--() DELETE l",
                    id=incident_id,
                    location=test_location,
                )
        monkeypatch.setattr(incident_store, "write_transaction", original_write_transaction)
        await driver.close()


@pytest.mark.parametrize(
    ("close_status", "update_first"),
    [
        (IncidentStatus.SILENCED, True),
        (IncidentStatus.SILENCED, False),
        (IncidentStatus.CLOSED, True),
        (IncidentStatus.CLOSED, False),
        (IncidentStatus.PROMOTED, True),
        (IncidentStatus.PROMOTED, False),
    ],
)
@pytest.mark.asyncio
async def test_signal_update_and_terminal_mutation_follow_lock_winner(
    monkeypatch, close_status, update_first
):
    driver = await _open_marked_driver()
    original_write_transaction = incident_store.write_transaction
    lock_acquired, release_first, wait_until_second_blocked = _install_controlled_writer(
        monkeypatch, driver, original_write_transaction
    )
    incident_id: str | None = None
    first: asyncio.Task | None = None
    second: asyncio.Task | None = None
    try:
        seeded = await incident_store.create_incident(
            IncidentCreateRequest(
                title="HN-I04 update-terminal race",
                kind="test.incident",
                severity="low",
                coords=(0.0, 0.0),
                sources=["hn-i04-test"],
                layer_hints=["hn-i04-test"],
            )
        )
        incident_id = seeded.id

        async def update():
            return await incident_store.apply_signal_update(
                incident_id,
                timeline_event=IncidentTimelineEvent(
                    t_offset_s=1.0, kind="signal", text="race-update"
                ),
                severity="high",
                sources_to_merge=["race-source"],
                layer_hints_to_merge=["race-hint"],
            )

        async def close():
            return await incident_store.close_incident(incident_id, close_status)

        first = asyncio.create_task(update() if update_first else close())
        await asyncio.wait_for(lock_acquired.wait(), timeout=10)
        second = asyncio.create_task(close() if update_first else update())
        await wait_until_second_blocked()
        release_first.set()
        first_result, second_result = await asyncio.gather(first, second)
        update_result, close_result = (
            (first_result, second_result) if update_first else (second_result, first_result)
        )

        assert close_result.status == "applied"
        assert close_result.incident is not None
        assert close_result.incident.status == close_status
        persisted = await incident_store.get_incident(incident_id)
        assert persisted is not None
        assert persisted.status == close_status
        if update_first:
            assert update_result.status == "applied"
            assert any(event.text == "race-update" for event in persisted.timeline)
            assert "race-source" in persisted.sources
        else:
            assert update_result.status == "unchanged"
            assert all(event.text != "race-update" for event in persisted.timeline)
            assert "race-source" not in persisted.sources
    finally:
        release_first.set()
        tasks = [task for task in (first, second) if task is not None]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if incident_id is not None:
            async with driver.session() as session:
                await session.run(
                    "MATCH (i:Incident {id: $id}) DETACH DELETE i", id=incident_id
                )
        monkeypatch.setattr(incident_store, "write_transaction", original_write_transaction)
        await driver.close()


@pytest.mark.parametrize(
    ("first_status", "second_status"),
    [
        (IncidentStatus.CLOSED, IncidentStatus.CLOSED),
        (IncidentStatus.PROMOTED, IncidentStatus.SILENCED),
    ],
)
@pytest.mark.asyncio
async def test_two_terminal_mutations_preserve_the_first_lock_winner(
    monkeypatch, first_status, second_status
):
    driver = await _open_marked_driver()
    original_write_transaction = incident_store.write_transaction
    lock_acquired, release_first, wait_until_second_blocked = _install_controlled_writer(
        monkeypatch, driver, original_write_transaction
    )
    incident_id: str | None = None
    first: asyncio.Task | None = None
    second: asyncio.Task | None = None
    try:
        seeded = await incident_store.create_incident(
            IncidentCreateRequest(
                title="HN-I04 terminal race",
                kind="test.incident",
                severity="low",
                coords=(0.0, 0.0),
                sources=["hn-i04-test"],
                layer_hints=["hn-i04-test"],
            )
        )
        incident_id = seeded.id
        first = asyncio.create_task(incident_store.close_incident(incident_id, first_status))
        await asyncio.wait_for(lock_acquired.wait(), timeout=10)
        second = asyncio.create_task(incident_store.close_incident(incident_id, second_status))
        await wait_until_second_blocked()
        release_first.set()
        first_result, second_result = await asyncio.gather(first, second)
        assert first_result.status == "applied"
        assert second_result.status == "unchanged"
        assert first_result.incident is not None
        assert second_result.incident is not None
        assert first_result.incident.status == second_result.incident.status == first_status
        assert first_result.incident.closed_ts == second_result.incident.closed_ts
        persisted = await incident_store.get_incident(incident_id)
        assert persisted is not None
        assert persisted.status == first_status
    finally:
        release_first.set()
        tasks = [task for task in (first, second) if task is not None]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if incident_id is not None:
            async with driver.session() as session:
                await session.run(
                    "MATCH (i:Incident {id: $id}) DETACH DELETE i", id=incident_id
                )
        monkeypatch.setattr(incident_store, "write_transaction", original_write_transaction)
        await driver.close()


@pytest.mark.asyncio
async def test_real_missing_incident_mutation_returns_not_found(monkeypatch):
    driver = await _open_marked_driver()
    original_get_client = neo4j_client.get_graph_client

    async def get_test_driver():
        return driver

    monkeypatch.setattr(neo4j_client, "get_graph_client", get_test_driver)
    try:
        result = await incident_store.close_incident(
            f"hn-i04-missing-{uuid4().hex}", IncidentStatus.CLOSED
        )
        assert result.status == "not_found"
        assert result.incident is None
    finally:
        monkeypatch.setattr(neo4j_client, "get_graph_client", original_get_client)
        await driver.close()


@pytest.mark.parametrize("replay_mode", ["rollback", "commit-ack"])
@pytest.mark.asyncio
async def test_managed_callback_replay_appends_only_once(monkeypatch, replay_mode):
    """Rollback and commit-ack retries reuse an operation receipt across transactions."""
    driver = await _open_marked_driver()
    original_get_client = neo4j_client.get_graph_client
    original_write_transaction = incident_store.write_transaction

    async def get_test_driver():
        return driver

    async def replay_write_transaction(callback, *, metadata=None):
        if replay_mode == "rollback":
            async with driver.session(default_access_mode=neo4j.WRITE_ACCESS) as session:
                transaction = await session.begin_transaction()
                rolled_back = await callback(transaction)
                assert rolled_back.status == "applied"
                await transaction.rollback()
        else:
            # Simulate a lost acknowledgement by committing and discarding the result.
            committed_but_unobserved = await original_write_transaction(
                callback, metadata=metadata
            )
            assert committed_but_unobserved.status == "applied"
        return await original_write_transaction(callback, metadata=metadata)

    monkeypatch.setattr(neo4j_client, "get_graph_client", get_test_driver)
    monkeypatch.setattr(incident_store, "write_transaction", replay_write_transaction)
    incident_id: str | None = None
    try:
        seeded = await incident_store.create_incident(
            IncidentCreateRequest(
                title="HN-I04 receipt replay",
                kind="test.incident",
                severity="low",
                coords=(0.0, 0.0),
                sources=["hn-i04-test"],
                layer_hints=["hn-i04-test"],
            )
        )
        incident_id = seeded.id
        result = await incident_store.apply_signal_update(
            incident_id,
            timeline_event=IncidentTimelineEvent(
                t_offset_s=1.0, kind="signal", text="single append"
            ),
            severity="high",
            sources_to_merge=["receipt-source"],
            layer_hints_to_merge=["receipt-hint"],
        )
        assert result.status == "applied"
        persisted = await incident_store.get_incident(incident_id)
        assert persisted is not None
        assert [event.text for event in persisted.timeline].count("single append") == 1
    finally:
        if incident_id is not None:
            async with driver.session() as session:
                await session.run(
                    "MATCH (i:Incident {id: $id}) DETACH DELETE i", id=incident_id
                )
        monkeypatch.setattr(incident_store, "write_transaction", original_write_transaction)
        monkeypatch.setattr(neo4j_client, "get_graph_client", original_get_client)
        await driver.close()
