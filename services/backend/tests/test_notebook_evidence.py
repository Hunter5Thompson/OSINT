"""Notebook passage identity and restrictions survive the public report interface."""

import json
from pathlib import Path

import httpx

from app.models.intel import IntelAnalysis
from app.models.report import ReportRecord
from app.services.intel_stream import stream_intel_query
from app.services.report_store import build_hydration_patch

PASSAGE = json.loads(
    (Path(__file__).parents[3] / "tests/fixtures/notebook-passage.json").read_text()
)


async def test_passage_survives_sse_and_report_persistence_contract():
    payload = {
        "query": "export restrictions",
        "analysis": "Attributed background.",
        "evidence_summary": [PASSAGE],
    }
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ) as client:
        events = [
            event async for event in stream_intel_query(query=payload["query"], client=client)
        ]
    result = json.loads(next(event["data"] for event in events if event["event"] == "result"))
    assert result["evidence_summary"][0] == PASSAGE
    patch = build_hydration_patch(IntelAnalysis.model_validate(result), country_name="Fixture")
    record = ReportRecord(
        id="fixture",
        title="Fixture",
        paragraph_num=1,
        stamp="test",
        **patch.model_dump(exclude_unset=True),
    )
    restored = ReportRecord.model_validate_json(record.model_dump_json())
    assert restored.evidence_summary[0].model_dump(mode="json") == PASSAGE
