"""Trace the real extraction/parser path without a provider or production sink."""

import asyncio
import json
import sys
import time
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

import config
from pipeline import ExtractionTransientError, _call_vllm


class Span:
    def __init__(self, recorder, kind, name, **fields):
        self.trace_id = fields.get("trace_id") or uuid.uuid4().hex
        self.span_id = uuid.uuid4().hex
        self.started = time.perf_counter()
        self.recorder = recorder
        self.kind = kind
        self.fields = fields
        recorder.events.append({"kind": kind, "phase": "start", "name": name, **fields})

    def finish(self, status="success", **fields):
        self.recorder.events.append({"kind": self.kind, "phase": "finish", "status": status,
                                     **self.fields, **fields})


class Recorder:
    def __init__(self):
        self.events = []

    def span(self, kind, name, **fields):
        return Span(self, kind, name, **fields)

    def close(self):
        pass


@pytest.fixture
def tracing_sink(monkeypatch):
    recorder = Recorder()
    values = config.Settings(_env_file=None).model_dump()
    values.update(spark_trace_endpoint="unix:/fixture", spark_trace_token_file="/fixture/token",
                  spark_trace_capture="metadata", spark_trace_target_id="spark",
                  spark_trace_spark_id="spark")
    settings = SimpleNamespace(**values)
    monkeypatch.setattr(config, "settings", settings)
    monkeypatch.setitem(sys.modules, "spark_trace_reporter",
                        SimpleNamespace(TraceReporter=lambda *args, **kwargs: recorder))
    adapter = sys.modules.get("tracing")
    if adapter is not None:
        monkeypatch.setattr(adapter, "settings", settings)
        monkeypatch.setattr(adapter, "_reporter", None)
    yield recorder, settings
    if adapter is not None:
        adapter.close_reporter()


@pytest.mark.parametrize("finish,content,status", [
    ("stop", '{"entities":[]}', "success"),
    ("length", "{}", "error"),
    ("stop", "bad-json", "error"),
])
async def test_real_extraction_reports_usage_and_parser_failures(
    tracing_sink, finish, content, status,
):
    recorder, settings = tracing_sink
    requests = []

    def provider(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={
            "model": "Qwen/Qwen3.8-27B", "usage": {"prompt_tokens": 11, "completion_tokens": 3},
            "choices": [{"finish_reason": finish, "message": {"content": content}}],
        })

    client_class = httpx.AsyncClient
    with patch("pipeline.httpx.AsyncClient", side_effect=lambda **kw: client_class(
        transport=httpx.MockTransport(provider), **kw,
    )):
        if status == "error":
            with pytest.raises(ExtractionTransientError):
                await _call_vllm("title", "body", "https://source.test", settings)
        else:
            assert await _call_vllm("title", "body", "https://source.test", settings) == {
                "entities": [],
            }
    terminal = [event for event in recorder.events if event["phase"] == "finish"]
    assert len(terminal) == 2, "extraction must emit terminal run and generation spans"
    assert all(event["status"] == status for event in terminal)
    generation = next(event for event in terminal if event["kind"] == "generation")
    assert generation["usage"]["input_tokens"] == 11
    assert generation["usage"]["output_tokens"] == 3
    assert generation["usage"]["cache_read_tokens"] is None
    assert generation["ttft_ms"] is None
    assert generation["spark_id"] == "spark"
    assert generation["input"] == requests[0]["messages"]
    assert requests[0]["max_tokens"] == 2000


@pytest.mark.parametrize("point", ["start", "finish"])
async def test_real_extraction_survives_telemetry_failure(tracing_sink, monkeypatch, point):
    recorder, settings = tracing_sink

    def fail(*args, **kwargs):
        raise RuntimeError("telemetry unavailable")

    if point == "start":
        monkeypatch.setattr(recorder, "span", fail)
    else:
        monkeypatch.setattr(Span, "finish", fail)

    calls = []

    def provider(request):
        calls.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    client_class = httpx.AsyncClient
    with patch("pipeline.httpx.AsyncClient", side_effect=lambda **kw: client_class(
        transport=httpx.MockTransport(provider), **kw,
    )):
        assert await _call_vllm("title", "body", "https://source.test", settings) == {}
    assert len(calls) == 1


@pytest.mark.parametrize("failure", [TimeoutError("fixture"), asyncio.CancelledError()])
async def test_telemetry_finish_failure_preserves_exception_identity(
    tracing_sink, monkeypatch, failure,
):
    import tracing

    def fail(*args, **kwargs):
        raise RuntimeError("finish unavailable")

    monkeypatch.setattr(Span, "finish", fail)

    @tracing.traced_extraction("fixture")
    async def extraction():
        raise failure

    with pytest.raises(type(failure)) as caught:
        await extraction()
    assert caught.value is failure


async def test_notebook_extraction_keeps_model_budget_timeout_and_unknown_usage(tracing_sink):
    from nlm_ingest.extract import extract_with_qwen
    from nlm_ingest.schemas import ExtractionSource

    recorder, _settings = tracing_sink
    requests = []

    def provider(request):
        requests.append(request)
        return httpx.Response(200, json={
            "model": "notebook-fixture", "choices": [{"message": {"content": "{}"}}],
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        extraction = await extract_with_qwen(
            ExtractionSource(notebook_id="nb1", source_id="report", source_kind="report",
                             text="fixture report"),
            {"title": "fixture"}, client, "https://provider.test", "notebook-fixture",
            timeout=37, max_tokens=8000,
        )
    assert extraction.notebook_id == "nb1"
    assert json.loads(requests[0].content)["max_tokens"] == 8000
    assert requests[0].extensions["timeout"]["read"] == 37
    terminal = [event for event in recorder.events if event["phase"] == "finish"]
    assert len(terminal) == 2
    generation = next(event for event in terminal if event["kind"] == "generation")
    assert generation["model"] == "notebook-fixture"
    assert generation["ttft_ms"] is None
    assert generation["usage"] == {
        "input_tokens": None, "output_tokens": None, "cache_read_tokens": None,
    }


async def test_scheduler_shutdown_flushes_reporter_despite_redis_close_failure(
    tracing_sink, monkeypatch,
):
    import scheduler
    import tracing

    recorder, _settings = tracing_sink
    failure = ValueError("redis close fixture")
    closed = []

    def close():
        closed.append(True)
        raise RuntimeError("optional reporter close fixture")

    monkeypatch.setattr(recorder, "close", close)
    monkeypatch.setattr(tracing, "_reporter", recorder)
    monkeypatch.setattr(scheduler, "create_scheduler", MagicMock())
    monkeypatch.setattr(scheduler.signal, "signal", MagicMock())
    monkeypatch.setattr(scheduler, "check_ingestion_llm", AsyncMock())
    monkeypatch.setattr(scheduler, "initial_collection_jobs", lambda: [])
    monkeypatch.setattr(scheduler, "_redis_client", SimpleNamespace(
        aclose=AsyncMock(side_effect=failure),
    ))
    monkeypatch.setattr(scheduler.asyncio, "Event", lambda: AsyncMock())
    with pytest.raises(ValueError) as caught:
        await scheduler.main()
    assert caught.value is failure
    assert closed == [True]
    assert tracing._reporter is None
