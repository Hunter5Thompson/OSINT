"""Current research metadata must survive the public report lifecycle."""

import json
from pathlib import Path

import httpx

from app.models.intel import IntelAnalysis
from app.models.report import ReportRecord
from app.services import intel_stream, report_store

FIXTURE = json.loads(
    (Path(__file__).parents[4] / "tests/fixtures/current-research.json").read_text()
)


def test_current_evidence_hydrates_and_persists_without_certifying_truth():
    analysis = IntelAnalysis(query="Iran", analysis="Attributed claims", **FIXTURE)
    patch = report_store.build_hydration_patch(analysis, country_name="Synthetic")
    record = ReportRecord(id="fixture", title="Fixture", paragraph_num=1, stamp="06·XI",
                          **patch.model_dump(exclude_none=True))
    params = report_store._report_params(record.id, 1, record.stamp, record)
    restored = report_store._row_to_report(
        {**params, "id": record.id, "created_at": "2026-11-06T14:35:00Z"}
    )
    result = restored.model_dump(mode="json")
    assert result["research_coverage"] == FIXTURE["research_coverage"]
    assert result["evidence_summary"] == FIXTURE["evidence_summary"]


async def test_research_mode_and_coverage_cross_the_backend_stream():
    def upstream(request):
        assert json.loads(request.content)["research_mode"] == "historical"
        return httpx.Response(200, json={"query":"Iran", "analysis":"Fixture", **FIXTURE})
    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
        events = [event async for event in intel_stream.stream_intel_query(
            query="Iran", research_mode="historical", client=client)]
    result = json.loads(next(e["data"] for e in events if e["event"] == "result"))
    assert result["research_coverage"] == FIXTURE["research_coverage"]
    assert result["evidence_summary"] == FIXTURE["evidence_summary"]
