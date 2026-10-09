"""Trace the public query entry and real LangGraph callbacks without live models."""

import asyncio
import sys
import time
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langgraph.graph import END, StateGraph

import config
from graph import workflow
from graph.state import AgentState


class Span:
    def __init__(self, recorder, kind, name, **fields):
        self.trace_id = fields.get("trace_id") or uuid.uuid4().hex
        self.span_id = uuid.uuid4().hex
        self.started = time.perf_counter()
        self.recorder, self.kind = recorder, kind
        self.fields = {"trace_id": self.trace_id, "span_id": self.span_id, **fields}
        recorder.events.append({"kind": kind, "phase": "start", "name": name, **self.fields})

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
    values["llm_model"] = config.settings.llm_model
    values.update(spark_trace_endpoint="unix:/fixture", spark_trace_token_file="/fixture/token",
                  spark_trace_capture="metadata", spark_trace_target_id="workstation-5090",
                  spark_trace_spark_id="")
    settings = SimpleNamespace(**values)
    monkeypatch.setattr(config, "settings", settings)
    monkeypatch.setitem(sys.modules, "spark_trace_reporter",
                        SimpleNamespace(TraceReporter=lambda *args, **kwargs: recorder))
    adapter = sys.modules.get("tracing")
    if adapter is not None:
        monkeypatch.setattr(adapter, "settings", settings)
        monkeypatch.setattr(adapter, "_reporter", None)
    yield recorder
    if adapter is not None:
        adapter.close_reporter()


class FixtureChatModel(BaseChatModel):
    @property
    def _llm_type(self):
        return "fixture"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if any(isinstance(message, ToolMessage) for message in messages):
            message = AIMessage(content="done", usage_metadata={
                "input_tokens": 4, "output_tokens": 2, "total_tokens": 6,
            })
        else:
            message = AIMessage(content="", tool_calls=[{"id": "tool1", "name": "probe",
                                                         "args": {}}], usage_metadata={
                "input_tokens": 3, "output_tokens": 1, "total_tokens": 4,
            })
        return ChatResult(generations=[ChatGeneration(message=message)],
                          llm_output={"model_name": "local-fixture"})


async def test_public_parallel_queries_capture_model_tool_and_direct_spans(
    tracing_sink, monkeypatch,
):
    @tool
    async def probe() -> str:
        """Return fixture evidence, including a directly invoked SDK completion."""
        async def create(**request):
            return SimpleNamespace(model_dump=lambda: {
                "model": "local-direct", "choices": [{"message": {"content": "fixture"},
                                                       "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1},
            })

        adapter = sys.modules.get("tracing")
        if adapter is None:
            await create(model="local-direct", messages=[])
        else:
            await adapter.trace_completion(create, model="local-direct", messages=[])
        return "evidence"

    async def model_node(state):
        return {"messages": [await FixtureChatModel().ainvoke(state["messages"])],
                "synthesis": "fixture result"}

    builder = StateGraph(AgentState)
    builder.add_node("model", model_node)
    builder.add_node("tools", workflow.tool_node_for_state)
    builder.set_entry_point("model")
    builder.add_conditional_edges("model", lambda state:
                                 "tools" if state["messages"][-1].tool_calls else END)
    builder.add_edge("tools", "model")
    monkeypatch.setattr(workflow, "react_graph", builder.compile())
    monkeypatch.setattr(workflow, "tools_for_state", lambda state: [probe])
    monkeypatch.setattr(workflow, "_ensure_graph_client", lambda: None)
    results = await asyncio.gather(workflow.run_intelligence_query("one"),
                                   workflow.run_intelligence_query("two"))
    assert all(result["analysis"] == "fixture result" for result in results)
    events = [event for event in tracing_sink.events if event["phase"] == "finish"]
    runs = [event for event in events if event["kind"] == "run"]
    assert len(runs) == 2, "public queries must emit independent terminal run spans"
    assert len({event["trace_id"] for event in runs}) == 2
    for run in runs:
        children = [event for event in events if event["trace_id"] == run["trace_id"]]
        generations = [event for event in children if event["kind"] == "generation"]
        tools = [event for event in children if event["kind"] == "tool"]
        assert len(generations) == 3
        assert len(tools) == 1
        assert all(event["status"] == "success" for event in children)
        direct = next(event for event in generations if event["model"] == "local-direct")
        assert direct["parent_span_id"] == tools[0]["span_id"]
        assert all(event["spark_id"] is None for event in generations)
        assert sum(event["usage"]["input_tokens"] for event in generations) == 9


@pytest.mark.parametrize("point", ["start", "finish"])
@pytest.mark.parametrize("outcome", ["success", "error", "cancelled"])
async def test_telemetry_failure_cannot_replace_a_public_query_result_or_exception(
    tracing_sink, monkeypatch, point, outcome,
):
    failure = TimeoutError("provider timeout") if outcome == "error" else asyncio.CancelledError()

    def telemetry_failure(*args, **kwargs):
        raise RuntimeError("telemetry unavailable")

    if point == "start":
        monkeypatch.setattr(tracing_sink, "span", telemetry_failure)
    else:
        monkeypatch.setattr(Span, "finish", telemetry_failure)

    calls = []

    async def invoke(state, **kwargs):
        calls.append(state["query"])
        if outcome != "success":
            raise failure
        return {"synthesis": "authoritative result"}

    monkeypatch.setattr(workflow, "_ensure_graph_client", lambda: None)
    monkeypatch.setattr(workflow, "react_graph", SimpleNamespace(ainvoke=invoke))
    if outcome == "success":
        result = await workflow.run_intelligence_query("fixture")
        assert result["analysis"] == "authoritative result"
    else:
        with pytest.raises(type(failure)) as caught:
            await workflow.run_intelligence_query("fixture")
        assert caught.value is failure
    assert calls == ["fixture"]


async def test_legacy_error_response_is_a_failed_trace(tracing_sink, monkeypatch):
    async def invoke(state, **kwargs):
        raise ValueError("legacy fixture")

    monkeypatch.setattr(workflow, "_ensure_graph_client", lambda: None)
    monkeypatch.setattr(workflow, "legacy_graph", SimpleNamespace(ainvoke=invoke))
    result = await workflow.run_intelligence_query("fixture", use_legacy=True)
    assert result["mode"] == "error"
    terminal = [event for event in tracing_sink.events if event["phase"] == "finish"]
    assert terminal[0]["status"] == "error"


@pytest.mark.parametrize("point", ["start", "finish"])
async def test_direct_completion_survives_telemetry_failure(tracing_sink, monkeypatch, point):
    import tracing

    expected = SimpleNamespace(choices=[])

    async def create(**request):
        return expected

    async def invoke(state, **kwargs):
        if point == "start":
            def fail(*args, **kwargs):
                raise RuntimeError("generation telemetry unavailable")
            monkeypatch.setattr(tracing_sink, "span", fail)
        else:
            def fail(*args, **kwargs):
                raise RuntimeError("generation finish unavailable")
            monkeypatch.setattr(Span, "finish", fail)
        assert await tracing.trace_completion(create, model="fixture", messages=[]) is expected
        return {"synthesis": "preserved"}

    monkeypatch.setattr(workflow, "_ensure_graph_client", lambda: None)
    monkeypatch.setattr(workflow, "react_graph", SimpleNamespace(ainvoke=invoke))
    assert (await workflow.run_intelligence_query("fixture"))["analysis"] == "preserved"


async def test_app_shutdown_flushes_reporter_without_replacing_resource_errors(
    tracing_sink, monkeypatch,
):
    import main
    import tracing

    failure = ValueError("retriever close fixture")
    closed = []

    def close():
        closed.append(True)
        raise RuntimeError("optional reporter close fixture")

    monkeypatch.setattr(tracing_sink, "close", close)
    monkeypatch.setattr(tracing, "_reporter", tracing_sink)
    monkeypatch.setattr(main._spatial_catalog, "load", lambda: None)
    monkeypatch.setattr(main.retriever, "close", AsyncMock(side_effect=failure))
    monkeypatch.setattr(main, "shutdown_graph_client", AsyncMock())
    with pytest.raises(ValueError) as caught:
        async with main.lifespan(main.app):
            pass
    assert caught.value is failure
    assert closed == [True]
    assert tracing._reporter is None
