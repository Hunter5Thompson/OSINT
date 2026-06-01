# services/backend/tests/test_intel_stream.py
import json

import httpx
import pytest

from app.services import intel_stream


@pytest.mark.asyncio
async def test_stream_emits_status_then_result(monkeypatch):
    async def fake_post(self, url, json):  # noqa: A002
        class R:
            def raise_for_status(self): ...
            def json(self):
                return {
                    "analysis": "Lage stabil",
                    "confidence": 0.8,
                    "threat_assessment": "MODERATE",
                    "sources_used": ["odin-country-almanac"],
                    "agent_chain": ["react_agent", "synthesis"],
                    "tool_trace": [],
                    "mode": "react",
                }

        return R()

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    events = [
        ev
        async for ev in intel_stream.stream_intel_query(
            query="Lage Deutschland",
            grounding_context="ctx",
            grounding_evidence=[{"x": 1}],
        )
    ]
    kinds = [e["event"] for e in events]
    assert kinds[:3] == ["status", "status", "status"]
    assert "result" in kinds and kinds[-1] == "done"
    result = json.loads(next(e["data"] for e in events if e["event"] == "result"))
    assert result["analysis"] == "Lage stabil"


@pytest.mark.asyncio
async def test_stream_emits_error_on_http_failure(monkeypatch):
    async def boom(self, url, json):  # noqa: A002
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx.AsyncClient, "post", boom)
    events = [ev async for ev in intel_stream.stream_intel_query(query="q")]
    assert any(e["event"] == "error" for e in events)
