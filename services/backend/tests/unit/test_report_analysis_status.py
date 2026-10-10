"""Saving a model result must preserve unavailable fields through report hydration."""

import json
from unittest.mock import AsyncMock

from app.models.intel import IntelAnalysis
from app.models.report import ReportRecord
from app.services import report_store
from tests.unit.test_analysis_status import SUMMARY


def analysis():
    return IntelAnalysis(
        query="synthetic",
        analysis="Synthetic report with missing fields",
        confidence=0.5,
        threat_assessment="MODERATE",
        assessment_status={
            "threat": "default",
            "confidence": "default",
            "issues": ["threat-missing", "confidence-missing"],
        },
        verification_status="unverified",
        evidence_summary=SUMMARY,
    )


def test_hydration_does_not_publish_default_metrics_as_read_values():
    patch = report_store.build_hydration_patch(analysis(), country_name="Synthetic test")
    metrics = {metric.label: metric for metric in patch.metrics}
    assert metrics["Threat"].value == "—"
    assert metrics["Confidence"].value == "—"
    assert patch.model_dump().get("assessment_status") == analysis().assessment_status.model_dump()
    assert patch.model_dump().get("verification_status") == "unverified"


def test_real_report_params_and_reader_preserve_field_status():
    patch = report_store.build_hydration_patch(analysis(), country_name="Synthetic test")
    record = ReportRecord(
        id="synthetic-report",
        paragraph_num=1,
        stamp="10·X",
        title="Synthetic",
        **patch.model_dump(exclude_none=True),
    )
    params = report_store._report_params(record.id, 1, record.stamp, record)
    assert json.loads(params.get("assessment_status_json", "null")) == {
        "threat": "default",
        "confidence": "default",
        "issues": ["threat-missing", "confidence-missing"],
    }
    hydrated = report_store._row_to_report(
        {
            **params,
            "id": record.id,
            "created_at": "2026-10-10T00:00:00Z",
            "updated_at": "2026-10-10T00:00:00Z",
        }
    )
    assert hydrated.model_dump().get("verification_status") == "unverified"
    assert (
        hydrated.model_dump().get("assessment_status") == (record.model_dump()["assessment_status"])
    )
    assert json.loads(params.get("evidence_summary_json", "null")) == SUMMARY
    assert hydrated.model_dump(mode="json").get("evidence_summary") == SUMMARY


def test_bad_status_metadata_remains_unknown_without_losing_the_report():
    report = report_store._row_to_report(
        {
            "id": "synthetic",
            "created_at": "2026-10-10T00:00:00Z",
            "assessment_status_json": "not-json",
            "verification_status": "verified",
        }
    )
    assert report.id == "synthetic"
    assert report.model_dump().get("assessment_status") is None
    assert report.model_dump().get("verification_status") is None


async def test_explicit_unknown_status_clears_previous_report_metadata(monkeypatch):
    old = ReportRecord(
        id="synthetic",
        paragraph_num=1,
        stamp="10·X",
        title="Synthetic",
        assessment_status=analysis().assessment_status,
        verification_status="unverified",
    )
    monkeypatch.setattr(report_store, "get_report", AsyncMock(return_value=old))
    captured = []

    async def write(query, params):
        captured.append(params)
        return [{**params, "id": old.id, "created_at": "2026-10-10T00:00:00Z"}]

    monkeypatch.setattr(report_store, "write_query", write)
    from app.models.report import ReportUpdateRequest

    updated = await report_store.update_report(
        old.id,
        ReportUpdateRequest(
            assessment_status=None,
            verification_status=None,
        ),
    )
    assert updated.assessment_status is None and updated.verification_status is None
    assert captured[0]["assessment_status_json"] is None
    assert captured[0]["verification_status"] is None


async def test_actual_message_writer_and_row_reader_keep_answer_metadata(monkeypatch):
    from app.models.report import ReportMessageCreate

    captured = []

    async def write(query, params):
        captured.append(params)
        return [{**params, "id": "synthetic-message"}]

    monkeypatch.setattr(report_store, "write_query", write)
    message = await report_store.append_report_message(
        "synthetic-report",
        ReportMessageCreate(
            role="munin",
            text="Synthetic answer",
            assessment_status=analysis().assessment_status,
            verification_status="unverified",
            evidence_summary=SUMMARY,
        ),
    )
    assert json.loads(captured[0].get("evidence_summary_json", "null")) == SUMMARY
    assert message.model_dump(mode="json").get("evidence_summary") == SUMMARY
    assert message.assessment_status == analysis().assessment_status


def test_sources_metric_counts_consumed_references_instead_of_provider_names():
    data = analysis().model_dump(mode="json")
    data["sources_used"] = ["fixture.example.invalid"]
    data["evidence_summary"] = [*SUMMARY, {**SUMMARY[0], "source_ref_id": "second-synthetic-ref"}]
    patch = report_store.build_hydration_patch(
        IntelAnalysis.model_validate(data), country_name="Synthetic"
    )
    metric = next(metric for metric in patch.metrics if metric.label == "Sources")
    assert metric.value == "2"
    assert metric.sub == "konsumierte Beleg-IDs"
