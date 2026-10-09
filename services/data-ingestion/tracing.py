"""Optional best-effort Spark spans; extraction results and errors stay authoritative."""

from __future__ import annotations

import asyncio
import atexit
import contextvars
import functools
import inspect
import logging

from config import settings

_log = logging.getLogger(__name__)
_reporter = None
_disabled_reported = False
_capture = contextvars.ContextVar("odin_extraction_trace", default=None)


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
            "odin-ingestion",
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
    if span is None:
        return
    try:
        span.finish(status, **fields)
    except Exception as exc:
        _log.warning("Spark tracing finish failed: %s", type(exc).__name__)


def record_request(payload):
    capture = _capture.get()
    if capture is not None:
        capture["request"] = payload


def record_response(data):
    capture = _capture.get()
    if capture is not None:
        capture["response"] = data


def traced_extraction(name):
    def decorate(fn):
        signature = inspect.signature(fn)

        @functools.wraps(fn)
        async def wrapped(*args, **kwargs):
            reporter = get_reporter()
            if reporter is None:
                return await fn(*args, **kwargs)
            run = generation = None
            try:
                bound = signature.bind(*args, **kwargs)
                config = bound.arguments.get("settings", settings)
                model = bound.arguments.get("vllm_model", config.ingestion_vllm_model)
                run = reporter.span("run", name, target_id="workflow")
                generation = reporter.span(
                    "generation", name, trace_id=run.trace_id, parent_span_id=run.span_id,
                    target_id=config.spark_trace_target_id,
                    spark_id=config.spark_trace_spark_id or None, model=model,
                )
            except Exception as exc:
                _log.warning("Spark tracing start failed: %s", type(exc).__name__)
                if run is None:
                    return await fn(*args, **kwargs)
            capture = {}
            context = _capture.set(capture)
            status = "success"
            error = None
            try:
                return await fn(*args, **kwargs)
            except BaseException as exc:
                status = "cancelled" if isinstance(exc, asyncio.CancelledError) else "error"
                error = {"type": type(exc).__name__, "message": str(exc)[:4000]}
                raise
            finally:
                _capture.reset(context)
                try:
                    response = capture.get("response") or {}
                    request = capture.get("request") or {}
                    usage = response.get("usage") or {} if isinstance(response, dict) else {}
                    choices = response.get("choices") or [] if isinstance(response, dict) else []
                    choice = choices[0] if choices and isinstance(choices[0], dict) else {}
                    _finish(
                        generation, status,
                        model=response.get("model", model) if isinstance(response, dict) else model,
                        input=request.get("messages"),
                        output=choice.get("message"),
                        requested_parameters={
                            k: v for k, v in request.items() if k not in ("messages", "model")
                        },
                        usage={
                            "input_tokens": usage.get("prompt_tokens"),
                            "output_tokens": usage.get("completion_tokens"),
                            "cache_read_tokens": (usage.get("prompt_tokens_details") or {}).get(
                                "cached_tokens"
                            ),
                        },
                        finish_reason=choice.get("finish_reason"),
                        ttft_ms=None,
                        error=error,
                    )
                except Exception as exc:
                    _finish(
                        generation, status, metadata={"telemetry_error": type(exc).__name__},
                        error=error,
                    )
                _finish(run, status, error=error)

        return wrapped

    return decorate
