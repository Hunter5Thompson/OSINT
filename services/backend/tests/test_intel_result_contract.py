import json
from pathlib import Path

import httpx
import pytest

from app.models.intel import IntelAnalysis
from app.services.intel_stream import stream_intel_query


async def test_failed_upstream_is_error_not_result():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                502,
                json={
                    "status": "failed",
                    "code": "INTEL_PIPELINE_FAILED",
                    "error": "Recherche fehlgeschlagen",
                },
            )
        )
    ) as client:
        events = [e async for e in stream_intel_query(query="test", client=client)]
    assert not any(e["event"] == "result" for e in events)
    error = json.loads(next(e["data"] for e in events if e["event"] == "error"))
    assert error["code"] == "INTEL_PIPELINE_FAILED"
    assert error["status"] == "failed"


@pytest.mark.parametrize("status,code", [(429, "MODEL_BUSY"), (504, "MODEL_TIMEOUT")])
async def test_pipeline_error_body_cannot_override_admission_or_timeout_status(status, code):
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(status, json={"code": "INTEL_PIPELINE_FAILED"})
    )) as client:
        events = [e async for e in stream_intel_query(query="test", client=client)]
    assert not any(e["event"] == "result" for e in events)
    error = json.loads(next(e["data"] for e in events if e["event"] == "error"))
    assert error["code"] == code
    assert error["status"] == "failed"


async def test_empty_contract_survives_sse():
    payload = {
        "query": "test",
        "analysis": "Keine Belege im Recherchelauf.",
        "status": "completed",
        "answerability": "insufficient_evidence",
        "confidence": None,
        "threat_assessment": None,
        "evidence_summary": [],
        "assessment_status": {"threat": "not_assessed", "confidence": "not_assessed", "issues": []},
    }
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ) as client:
        events = [e async for e in stream_intel_query(query="test", client=client)]
    data = json.loads(next(e["data"] for e in events if e["event"] == "result"))
    assert data["answerability"] == "insufficient_evidence"
    assert data["confidence"] is None and data["threat_assessment"] is None


PAYLOADS = json.loads(
    (Path(__file__).parents[3] / "tests/fixtures/reviewed-claims-47.json").read_text()
)


@pytest.mark.parametrize("p", PAYLOADS, ids=lambda p: p["review"]["candidate_id"])
async def test_backend_retains_review(p):
    result = IntelAnalysis.model_validate(
        {
            "query": "test",
            "analysis": "text",
            "evidence_summary": [
                {
                    "source_ref_id": "parent",
                    "provider": p["provider"],
                    "source_type": p["source_type"],
                    "verification_status": "unverified",
                    "review": p["review"],
                    "evidence_id": "claim",
                }
            ],
        }
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=result.model_dump(mode="json"))
        )
    ) as client:
        events = [event async for event in stream_intel_query(query="test", client=client)]
    public = json.loads(next(event["data"] for event in events if event["event"] == "result"))
    actual = public["evidence_summary"][0]["review"]
    assert actual["qualification_note"] == p["review"]["qualification_note"]
    assert actual["candidate_id"] == p["review"]["candidate_id"]
    assert len(actual["evidence"]) == len(p["review"]["evidence"])
    for before, after in zip(p["review"]["evidence"], actual["evidence"], strict=True):
        for key in before:
            assert after[key] == before[key]


async def test_no_assessment_clears_previous_report_confidence(monkeypatch):
    from unittest.mock import AsyncMock

    from app.models.report import ReportRecord
    from app.services import report_store

    old = ReportRecord(
        id="fixture", paragraph_num=1, stamp="test", title="Previous", confidence=0.8
    )
    monkeypatch.setattr(report_store, "get_report", AsyncMock(return_value=old))
    writer = AsyncMock(return_value=[])
    monkeypatch.setattr(report_store, "write_query", writer)
    analysis = IntelAnalysis(
        query="test",
        analysis="No evidence in this run.",
        confidence=None,
        assessment_status={"threat": "not_assessed", "confidence": "not_assessed", "issues": []},
        threat_assessment=None,
        evidence_summary=[],
    )
    patch = report_store.build_hydration_patch(analysis, country_name="Fixture")
    await report_store.update_report("fixture", patch)
    properties = writer.call_args.args[1]["properties"]
    assert properties["confidence"] is None
    assert (
        json.loads(properties["assessment_status_json"])["threat"] == "not_assessed"
    )
