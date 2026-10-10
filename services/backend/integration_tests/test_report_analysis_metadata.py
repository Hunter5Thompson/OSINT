"""Opt-in real Neo4j gate for G06; explicit isolated marker, own records only."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from neo4j import AsyncGraphDatabase

from app.models.intel import IntelAnalysis
from app.models.report import ReportCreateRequest, ReportMessageCreate, ReportUpdateRequest

SUMMARY = [
    {
        "source_ref_id": "synthetic-reference",
        "source_type": "dataset",
        "provider": "fixture.example.invalid",
        "published_at": None,
        "observed_at": "2020-01-01T00:00:00Z",
        "ingested_at": "2026-10-10T00:00:00Z",
        "verification_status": "unverified",
    }
]


@pytest.fixture
async def case(monkeypatch):
    uri = os.environ.get("HN_TEST_NEO4J_URI")
    password = os.environ.get("HN_TEST_NEO4J_PASSWORD")
    if not uri or not password:
        pytest.fail("Explicit isolated HN Neo4j credentials are required")
    monkeypatch.setenv("NEO4J_PASSWORD", "test-settings-only")
    from app.services import report_store

    driver = AsyncGraphDatabase.driver(uri, auth=("neo4j", password))
    report_id = f"hn-g06-{uuid4().hex}"
    message_ids: list[str] = []
    verified = False
    try:
        await driver.verify_connectivity()
        async with driver.session() as session:
            result = await session.run(
                "MATCH (:HNTestInstance {id: $marker}) RETURN true AS isolated",
                marker="hn-g06-isolated-20261010",
            )
            if await result.single() is None:
                pytest.fail("G06 isolated database marker is missing")
        verified = True

        async def query(cypher, params):
            async with driver.session() as session:
                result = await session.run(cypher, params)
                return await result.data()

        monkeypatch.setattr(report_store, "read_query", query)
        monkeypatch.setattr(report_store, "write_query", query)
        from app.cypher.report_write import REPORT_CREATE

        record = ReportCreateRequest(
            title="Synthetic isolated report", body_paragraphs=["Original body"]
        )
        params = report_store._report_params(report_id, 1, "10·X", record)
        params["now"] = "2026-10-10T00:00:00Z"
        await query(REPORT_CREATE, params)
        yield report_store, report_id, message_ids
    finally:
        if verified:
            async with driver.session() as session:
                await session.run(
                    "MATCH (m:Message) WHERE m.id IN $ids DETACH DELETE m", ids=message_ids
                )
                await session.run("MATCH (r:Report {id: $id}) DETACH DELETE r", id=report_id)
        await driver.close()


@pytest.mark.parametrize("summary", [None, [], SUMMARY])
async def test_dossier_metadata_round_trip_and_explicit_unknown_clear(case, summary):
    store, report_id, _ = case
    analysis = IntelAnalysis(
        query="synthetic",
        analysis="Synthetic analysis",
        evidence_summary=summary,
        assessment_status={
            "threat": "default",
            "confidence": "default",
            "issues": ["threat-missing"],
        },
        verification_status="unverified",
    )
    patch = store.build_hydration_patch(analysis, country_name="Synthetic")
    updated = await store.update_report(report_id, patch)
    assert updated is not None
    read = await store.get_report(report_id)
    assert read.model_dump(mode="json")["evidence_summary"] == summary
    assert read.assessment_status == analysis.assessment_status
    assert read.verification_status == "unverified"
    await store.update_report(
        report_id,
        ReportUpdateRequest(
            assessment_status=None,
            verification_status=None,
            evidence_summary=None,
        ),
    )
    cleared = await store.get_report(report_id)
    assert cleared.evidence_summary is None and cleared.assessment_status is None
    assert cleared.verification_status is None


async def test_chat_metadata_is_attached_to_message_without_relabelling_dossier(case):
    store, report_id, message_ids = case
    message = await store.append_report_message(
        report_id,
        ReportMessageCreate(
            role="munin",
            text="Synthetic later answer",
            evidence_summary=SUMMARY,
            assessment_status={
                "threat": "declared",
                "confidence": "default",
                "issues": ["confidence-missing"],
            },
            verification_status="unverified",
        ),
    )
    assert message is not None
    message_ids.append(message.id)
    messages = await store.list_report_messages(report_id)
    assert len(messages) == 1
    assert messages[0].model_dump(mode="json")["evidence_summary"] == SUMMARY
    assert messages[0].assessment_status == message.assessment_status
    assert messages[0].verification_status == "unverified"
    report = await store.get_report(report_id)
    assert report.body_paragraphs == ["Original body"]
    assert report.evidence_summary is None and report.assessment_status is None
