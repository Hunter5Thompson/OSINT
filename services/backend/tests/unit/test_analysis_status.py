"""G06 status crosses the real shared SSE serializer and history model."""

import json

import httpx
import pytest
from pydantic import ValidationError

from app.models.intel import IntelAnalysis
from app.services.intel_stream import stream_intel_query

STATUS = {"threat": "default", "confidence": "declared", "issues": ["threat-invalid"]}
SUMMARY = [
    {
        "source_ref_id": "synthetic-ref",
        "source_type": "dataset",
        "provider": "fixture.example.invalid",
        "published_at": None,
        "observed_at": "2020-01-01T00:00:00Z",
        "ingested_at": "2026-10-10T00:00:00Z",
        "verification_status": "unverified",
    }
]


@pytest.mark.asyncio
async def test_upstream_origin_and_verification_survive_shared_sse():
    def upstream(request):
        return httpx.Response(
            200,
            json={
                "analysis": "synthetic",
                "confidence": 0.3,
                "threat_assessment": "MODERATE",
                "sources_used": ["fixture.example.invalid"],
                "assessment_status": STATUS,
                "verification_status": "unverified",
                "evidence_summary": SUMMARY,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
        events = [event async for event in stream_intel_query(query="synthetic", client=client)]
    wire = json.loads(next(event["data"] for event in events if event["event"] == "result"))
    assert wire.get("assessment_status") == STATUS
    assert wire.get("verification_status") == "unverified"
    hydrated = IntelAnalysis.model_validate(wire).model_dump(mode="json")
    assert hydrated.get("assessment_status") == STATUS
    assert hydrated["confidence"] == 0.3
    assert wire.get("evidence_summary") == SUMMARY
    assert hydrated.get("evidence_summary") == SUMMARY


async def test_report_scoped_stream_persists_assessment_and_source_metadata(monkeypatch):
    from unittest.mock import AsyncMock

    from app.services import report_store

    update = AsyncMock(return_value=object())
    monkeypatch.setattr(report_store, "get_report", AsyncMock(return_value=object()))
    monkeypatch.setattr(report_store, "update_report", update)
    append = AsyncMock()
    monkeypatch.setattr(report_store, "append_report_message", append)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "analysis": "synthetic",
                    "assessment_status": STATUS,
                    "verification_status": "unverified",
                    "evidence_summary": SUMMARY,
                },
            )
        )
    ) as client:
        events = [
            event
            async for event in stream_intel_query(
                query="synthetic", report_id="synthetic", client=client
            )
        ]
    assert any(event["event"] == "result" for event in events)
    patch = append.await_args.args[1].model_dump(mode="json")
    assert patch["role"] == "munin"
    assert patch.get("assessment_status") == STATUS
    assert patch.get("verification_status") == "unverified"
    assert patch.get("evidence_summary") == SUMMARY
    # The answer metadata belongs to this chat message, not to an older dossier body.
    assert "evidence_summary" not in update.await_args.args[1].model_fields_set


def test_legacy_result_does_not_gain_a_declared_or_verified_status():
    result = IntelAnalysis(query="synthetic", analysis="old upstream")
    assert result.model_dump().get("assessment_status") is None
    assert result.model_dump().get("verification_status") is None


@pytest.mark.parametrize("axis", ["published_at", "observed_at", "ingested_at"])
def test_numeric_public_time_value_cannot_become_an_invented_epoch_date(axis):
    with pytest.raises(ValidationError):
        IntelAnalysis(
            query="synthetic", analysis="synthetic", evidence_summary=[{**SUMMARY[0], axis: 0}]
        )
