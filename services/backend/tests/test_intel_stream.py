# services/backend/tests/test_intel_stream.py
import json

import pytest

from app.services import intel_stream


class _FakeResponse:
    def raise_for_status(self):
        return None

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


class _FakeClient:
    def __init__(self):
        self.calls = []

    async def post(self, url, json, timeout=None):  # noqa: A002
        self.calls.append((url, json, timeout))
        return _FakeResponse()


@pytest.mark.asyncio
async def test_stream_emits_status_then_result_with_shared_client():
    client = _FakeClient()

    events = [
        ev
        async for ev in intel_stream.stream_intel_query(
            query="Lage Deutschland",
            grounding_context="ctx",
            grounding_evidence=[{"x": 1}],
            client=client,
        )
    ]
    kinds = [e["event"] for e in events]
    assert kinds[0] == "status"
    statuses = [json.loads(e["data"]) for e in events if e["event"] == "status"]
    assert statuses == [{"agent": "intelligence", "status": "processing"}]
    assert "result" in kinds and kinds[-1] == "done"
    result = json.loads(next(e["data"] for e in events if e["event"] == "result"))
    assert result["analysis"] == "Lage stabil"
    assert client.calls[0][2] == 300.0


@pytest.mark.asyncio
async def test_stream_emits_error_on_http_failure():
    class FailingClient:
        async def post(self, url, json, timeout=None):  # noqa: A002
            raise intel_stream.httpx.ConnectError("down")

    events = [ev async for ev in intel_stream.stream_intel_query(query="q", client=FailingClient())]
    assert any(e["event"] == "error" for e in events)


async def test_total_deadline_cancels_slow_upstream_and_reports_timeout(monkeypatch):
    import asyncio

    from app.config import settings

    monkeypatch.setattr(settings, "model_timeout_s", 0.01)
    closed = asyncio.Event()

    class StalledClient:
        async def post(self, *args, **kwargs):
            try:
                await asyncio.Event().wait()
            finally:
                closed.set()

    async def collect():
        return [e async for e in intel_stream.stream_intel_query(query="q", client=StalledClient())]

    events = await asyncio.wait_for(collect(), 1)
    assert closed.is_set()
    error = next(json.loads(e["data"]) for e in events if e["event"] == "error")
    assert error["code"] == "MODEL_TIMEOUT"
    assert not any(e["event"] == "result" for e in events)
