"""Opt-in real Neo4j gate for G06; explicit isolated marker, own records only."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
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
NOTEBOOK_SUMMARY = [json.loads(
    (Path(__file__).parents[3] / "tests/fixtures/notebook-passage.json").read_text()
)]


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


@pytest.mark.parametrize("summary", [None, [], SUMMARY, NOTEBOOK_SUMMARY])
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


@pytest.mark.parametrize("operation", ["create", "update"])
@pytest.mark.parametrize("confidence", [None, 0.0, 0.73])
async def test_confidence_survives_every_report_projection(case, operation, confidence):
    store, _, _ = case
    scope_key = f"review:{uuid4().hex}"
    created = None
    try:
        created = await store.create_report(
            ReportCreateRequest(
                title="Null confidence roundtrip",
                scope_key=scope_key,
                confidence=confidence if operation == "create" else 0.8,
            )
        )
        result = created
        if operation == "update":
            result = await store.update_report(
                created.id, ReportUpdateRequest(confidence=confidence)
            )
        assert result.confidence == confidence
        assert (await store.get_report(created.id)).confidence == confidence
        assert (await store.get_report_by_scope(scope_key)).confidence == confidence
        assert (
            next(r for r in await store.list_reports() if r.id == created.id).confidence
            == confidence
        )
        # An unrelated edit must not turn absence into a declared numeric value.
        renamed = await store.update_report(created.id, ReportUpdateRequest(title="Renamed"))
        assert renamed.confidence == confidence
        assert (await store.get_report(created.id)).confidence == confidence
    finally:
        if created is not None:
            await store.delete_report(created.id)


async def test_saved_briefing_chat_keeps_original_review_after_second_save(case, monkeypatch):
    from app.models.almanac import BriefingSaveRequest
    from app.routers import almanac

    store, report_id, message_ids = case
    original = await store.get_report(report_id)
    monkeypatch.setattr(almanac, "get_or_create_report_by_scope", AsyncMock(return_value=original))

    async def append(rid, payload):
        message = await store.append_report_message(rid, payload)
        message_ids.append(message.id)
        return message

    monkeypatch.setattr(almanac, "append_report_message", append)
    context = SimpleNamespace(
        country=SimpleNamespace(name="Fixture", capital=None),
        token=SimpleNamespace(scope_key=f"review:{report_id}"),
        legacy_scope_keys=(),
    )
    payload = json.loads(
        (Path(__file__).parents[3] / "tests/fixtures/reviewed-claims-47.json").read_text()
    )[0]
    reviewed = IntelAnalysis(
        query="fixture",
        analysis="Reviewed fixture answer",
        confidence=0.3,
        assessment_status={"threat": "declared", "confidence": "declared", "issues": []},
        verification_status="unverified",
        evidence_summary=[
            {
                "source_ref_id": "parent",
                "evidence_id": "claim-fixture",
                "source_type": "notebooklm",
                "provider": payload["provider"],
                "review": payload["review"],
                "verification_status": "unverified",
            }
        ],
    )
    abstention = IntelAnalysis(
        query="fixture",
        analysis="No evidence in this research run.",
        confidence=None,
        evidence_summary=[],
        verification_status="unverified",
        assessment_status={"threat": "not_assessed", "confidence": "not_assessed", "issues": []},
    )
    for analysis in [reviewed, abstention]:
        await almanac._save_resolved_country_briefing(
            context, BriefingSaveRequest(analysis=analysis)
        )
    messages = await store.list_report_messages(report_id)
    assert len(messages) == 2
    for message, analysis in zip(messages, [reviewed, abstention], strict=True):
        assert message.evidence_summary == analysis.evidence_summary
        assert message.assessment_status == analysis.assessment_status
        assert message.verification_status == analysis.verification_status
    final = await store.get_report(report_id)
    assert final.evidence_summary == []
    assert final.confidence is None


async def test_current_research_survives_save_reload_chat_and_explicit_clear(case):
    from app.models.research import ResearchCoverage

    store, report_id, message_ids = case
    fixture = json.loads(
        (Path(__file__).parents[3] / "tests/fixtures/current-research.json").read_text()
    )
    analysis = IntelAnalysis(query="synthetic", analysis="Current fixture", **fixture)
    patch = store.build_hydration_patch(analysis, country_name="Synthetic")
    await store.update_report(report_id, patch)
    saved = await store.get_report(report_id)
    assert saved.research_coverage == ResearchCoverage.model_validate(fixture["research_coverage"])
    assert saved.model_dump(mode="json")["evidence_summary"] == fixture["evidence_summary"]
    message = await store.append_report_message(report_id, ReportMessageCreate(
        role="munin", text="Later current answer", **fixture))
    message_ids.append(message.id)
    read_message = (await store.list_report_messages(report_id))[0]
    assert read_message.research_coverage == saved.research_coverage
    await store.update_report(report_id, ReportUpdateRequest(research_coverage=None))
    assert (await store.get_report(report_id)).research_coverage is None
    assert (await store.list_report_messages(report_id))[0].research_coverage is not None


async def test_disjoint_concurrent_patches_both_survive(case, monkeypatch):
    store, report_id, _ = case
    original_read = store.read_query
    barrier = asyncio.Barrier(2)

    async def overlapping_read(query, params):
        rows = await original_read(query, params)
        # Force the old read/merge/write path to read the same snapshot. Atomic
        # PATCH does not need this read and is checked by the same final state.
        await asyncio.wait_for(barrier.wait(), timeout=5)
        return rows

    with monkeypatch.context() as m:
        m.setattr(store, "read_query", overlapping_read)
        await asyncio.gather(
            store.update_report(report_id, ReportUpdateRequest(title="Concurrent title")),
            store.update_report(report_id, ReportUpdateRequest(confidence=0.37)),
        )
    result = await store.get_report(report_id)
    assert result.title == "Concurrent title"
    assert result.confidence == 0.37


async def test_delete_winning_before_patch_does_not_resurrect_report(case, monkeypatch):
    store, report_id, _ = case
    original_write = store.write_query
    from app.cypher.report_write import REPORT_DELETE

    async def delete_before_write(query, params):
        await original_write(REPORT_DELETE, {"report_id": report_id})
        return await original_write(query, params)

    with monkeypatch.context() as m:
        m.setattr(store, "write_query", delete_before_write)
        result = await store.update_report(report_id, ReportUpdateRequest(title="Too late"))
    assert result is None
    assert await store.get_report(report_id) is None


@pytest.mark.parametrize("patch", [{}, {"title": None, "findings": None}])
async def test_empty_or_ordinary_null_patch_never_writes(case, monkeypatch, patch):
    store, report_id, _ = case
    before = await store.get_report(report_id)
    with monkeypatch.context() as m:
        no_writes = AsyncMock(side_effect=AssertionError("no-op patch issued a write"))
        m.setattr(store, "write_query", no_writes)
        after = await store.update_report(report_id, ReportUpdateRequest(**patch))
    assert before == after


async def test_new_dossier_is_empty_after_create_and_reload(case):
    store, _, _ = case
    created = None
    try:
        created = await store.create_report(ReportCreateRequest())
        for report in [created, await store.get_report(created.id)]:
            assert report.confidence is None
            assert report.findings == []
            assert report.metrics == []
            assert report.margin == []
            assert report.sources == []
            assert report.body_paragraphs == []
            assert report.body_title == ""
    finally:
        if created is not None:
            await store.delete_report(created.id)
