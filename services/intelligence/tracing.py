"""Optional LangGraph trace adapter; callbacks observe, never change the workflow."""

from __future__ import annotations

import asyncio
import atexit
import contextvars
import functools
import logging
import time

from langchain_core.callbacks import BaseCallbackHandler

from config import settings

_reporter = None
_disabled_reported = False
_current = contextvars.ContextVar("odin_query_trace", default=None)
_log = logging.getLogger(__name__)


def get_reporter():
    global _reporter, _disabled_reported
    if _reporter is not None:
        return _reporter
    if not settings.spark_trace_endpoint:
        return None
    try:
        from spark_trace_reporter import TraceReporter

        _reporter = TraceReporter(
            settings.spark_trace_endpoint,
            settings.spark_trace_token_file,
            "odin-intelligence",
            settings.spark_trace_capture,
            project="odin",
        )
        atexit.register(close_reporter)
        return _reporter
    except Exception as exc:
        if not _disabled_reported:
            _log.warning("Spark tracing unavailable: %s", type(exc).__name__)
            _disabled_reported = True
        return None


def close_reporter():
    global _reporter
    reporter, _reporter = _reporter, None
    if reporter is not None:
        try:
            reporter.close()
        except Exception as exc:
            _log.warning("Spark tracing close failed: %s", type(exc).__name__)


def _finish(span, status, **fields):
    try:
        span.finish(status, **fields)
    except Exception as exc:
        _log.warning("Spark tracing finish failed: %s", type(exc).__name__)


def _usage(message):
    usage = getattr(message, "usage_metadata", None) or {}
    raw = (getattr(message, "response_metadata", None) or {}).get("token_usage") or {}
    return {
        "input_tokens": usage.get("input_tokens", raw.get("prompt_tokens")),
        "output_tokens": usage.get("output_tokens", raw.get("completion_tokens")),
        "cache_read_tokens": (usage.get("input_token_details") or {}).get(
            "cache_read", (raw.get("prompt_tokens_details") or {}).get("cached_tokens")
        ),
    }


class OdinTraceCallback(BaseCallbackHandler):
    run_inline = True
    raise_error = False

    def __init__(self, reporter, root):
        self.reporter, self.root = reporter, root
        self.parents, self.spans, self.first = {}, {}, {}

    def _parent(self, parent):
        seen = set()
        while parent and parent not in seen:
            seen.add(parent)
            if parent in self.spans:
                return self.spans[parent].span_id
            parent = self.parents.get(parent)
        return self.root.span_id

    def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, **kwargs):
        self.parents[run_id] = parent_run_id

    def on_chat_model_start(self, serialized, messages, *, run_id, parent_run_id=None, **kwargs):
        self.parents[run_id] = parent_run_id
        params = kwargs.get("invocation_params") or {}
        model = params.get("model_name") or params.get("model") or settings.llm_model
        self.spans[run_id] = self.reporter.span(
            "generation",
            str(model),
            trace_id=self.root.trace_id,
            parent_span_id=self._parent(parent_run_id),
            target_id=settings.spark_trace_target_id,
            spark_id=settings.spark_trace_spark_id or None,
            model=str(model),
            input=[[{"role": m.type, "content": m.content} for m in batch] for batch in messages],
            requested_parameters={
                k: v for k, v in params.items() if k not in ("messages", "api_key")
            },
        )

    def on_llm_new_token(self, token, *, run_id, **kwargs):
        if token and run_id not in self.first:
            self.first[run_id] = time.perf_counter()

    def on_llm_end(self, response, *, run_id, **kwargs):
        span = self.spans.get(run_id)
        if not span:
            return
        generation = (
            response.generations[0][0] if response.generations and response.generations[0] else None
        )
        message = getattr(generation, "message", None)
        meta = getattr(message, "response_metadata", None) or {}
        llm_meta = response.llm_output or {}
        model = (
            meta.get("model_name")
            or meta.get("model")
            or llm_meta.get("model_name")
            or llm_meta.get("model")
        )
        fields = dict(
            output={
                "content": getattr(message, "content", getattr(generation, "text", None)),
                "tool_calls": getattr(message, "tool_calls", []),
            },
            usage=_usage(message),
            finish_reason=meta.get("finish_reason"),
            ttft_ms=(self.first[run_id] - span.started) * 1000 if run_id in self.first else None,
            timing_source="content-callback" if run_id in self.first else "non-streaming",
        )
        if model:
            fields["model"] = str(model)
        span.finish("success", **fields)

    def on_llm_error(self, error, *, run_id, **kwargs):
        self._error(run_id, error)

    def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None, **kwargs):
        self.parents[run_id] = parent_run_id
        name = (serialized or {}).get("name", "tool")
        self.spans[run_id] = self.reporter.span(
            "tool",
            str(name),
            trace_id=self.root.trace_id,
            parent_span_id=self._parent(parent_run_id),
            input=kwargs.get("inputs", input_str),
        )

    def on_tool_end(self, output, *, run_id, **kwargs):
        span = self.spans.get(run_id)
        if span:
            status = "error" if getattr(output, "status", None) == "error" else "success"
            span.finish(status, output=getattr(output, "content", output))

    def on_tool_error(self, error, *, run_id, **kwargs):
        self._error(run_id, error)

    def _error(self, run_id, error):
        span = self.spans.get(run_id)
        if span:
            span.finish(
                "cancelled" if isinstance(error, asyncio.CancelledError) else "error",
                error={"type": type(error).__name__, "message": str(error)[:4000]},
            )


def trace_kwargs():
    current = _current.get()
    return {"config": {"callbacks": [current[1]]}} if current else {}


def traced_query(fn):
    @functools.wraps(fn)
    async def wrapped(*args, **kwargs):
        reporter = get_reporter()
        if reporter is None:
            return await fn(*args, **kwargs)
        try:
            root = reporter.span(
                "run", "intelligence-query", input=args[0] if args else kwargs.get("query")
            )
            callback = OdinTraceCallback(reporter, root)
        except Exception as exc:
            _log.warning("Spark tracing start failed: %s", type(exc).__name__)
            return await fn(*args, **kwargs)
        token = _current.set((root, callback))
        try:
            result = await fn(*args, **kwargs)
            failed = isinstance(result, dict) and (
                result.get("error") or result.get("mode") == "error"
            )
            _finish(root, "error" if failed else "success", output=result)
            return result
        except BaseException as exc:
            _finish(
                root, "cancelled" if isinstance(exc, asyncio.CancelledError) else "error",
                error={"type": type(exc).__name__, "message": str(exc)[:4000]},
            )
            raise
        finally:
            _current.reset(token)

    return wrapped


async def trace_completion(create, **request):
    current = _current.get()
    if current is None:
        return await create(**request)
    root, callback = current
    try:
        parent = root.span_id
        try:
            from langchain_core.runnables.config import var_child_runnable_config

            config = var_child_runnable_config.get() or {}
            manager = config.get("callbacks")
            parent = callback._parent(getattr(manager, "parent_run_id", None))
        except (ImportError, AttributeError):
            pass
        span = callback.reporter.span(
            "generation", request.get("model", "direct-completion"),
            trace_id=root.trace_id, parent_span_id=parent,
            target_id=settings.spark_trace_target_id,
            spark_id=settings.spark_trace_spark_id or None,
            model=request.get("model", "unknown"), input=request.get("messages"),
            requested_parameters={k: v for k, v in request.items()
                                  if k not in ("model", "messages")},
        )
    except Exception as exc:
        _log.warning("Spark tracing generation start failed: %s", type(exc).__name__)
        return await create(**request)
    try:
        result = await create(**request)
    except BaseException as exc:
        _finish(
            span, "cancelled" if isinstance(exc, asyncio.CancelledError) else "error",
            error={"type": type(exc).__name__, "message": str(exc)[:4000]},
        )
        raise
    try:
        raw = result.model_dump()
        choice = (raw.get("choices") or [{}])[0]
        usage = raw.get("usage") or {}
        _finish(
            span, "success",
            model=raw.get("model", request.get("model", "unknown")),
            output=choice.get("message"),
            usage={
                "input_tokens": usage.get("prompt_tokens"),
                "output_tokens": usage.get("completion_tokens"),
                "cache_read_tokens": (usage.get("prompt_tokens_details") or {}).get(
                    "cached_tokens"
                ),
            },
            finish_reason=choice.get("finish_reason"),
            ttft_ms=None,
        )
    except Exception as exc:
        _finish(span, "success", ttft_ms=None, metadata={"telemetry_error": type(exc).__name__})
    return result
