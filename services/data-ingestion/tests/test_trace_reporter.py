"""Exercise the baked reporter's bounded transport, capture and failure contract."""

import threading
import time
from unittest.mock import patch

from spark_trace_reporter import TraceReporter


def test_full_queue_drops_traces_and_shutdown_stays_bounded(tmp_path):
    gate = threading.Event()
    token = tmp_path / "token"
    token.write_text("fixture-only")
    with patch.object(TraceReporter, "_send", side_effect=lambda *_: gate.wait(1)):
        reporter = TraceReporter("unix:/fixture", token, "fixture")
        try:
            start = time.monotonic()
            for n in range(200):
                reporter.emit({"event_id": str(n)})
            assert time.monotonic() - start < 0.5
            assert reporter.dropped_total > 0
            start = time.monotonic()
            reporter.close(0.01)
            assert time.monotonic() - start < 0.2
        finally:
            gate.set()
            reporter.close(2)
    assert not reporter._worker.is_alive()


def test_metadata_omits_text_and_text_capture_scrubs_keys_and_binary(tmp_path):
    token = tmp_path / "token"
    token.write_text("fixture-only")
    for capture in ("metadata", "text"):
        sent = []
        with patch.object(TraceReporter, "_send", side_effect=lambda path, value, captured=sent:
                          captured.append((path, value))):
            reporter = TraceReporter("unix:/fixture", token, "fixture", capture=capture)
            try:
                span = reporter.span("generation", "fixture", input={
                    "image": "data:image/png;base64,private-binary",
                    "api_key": "private-key", "text": "😀" * 30000,
                })
                span.finish("success", output="private output", usage={"output_tokens": 3})
            finally:
                reporter.close(2)
        events = [value for path, value in sent if path.endswith("/events")]
        assert len(events) == 2
        if capture == "metadata":
            assert all("input" not in event and "output" not in event for event in events)
        else:
            first = events[0]
            assert first["input"]["api_key"] == "[redacted]"
            assert first["input"]["image"] == "[binary content omitted]"
            assert len(first["input"]["text"].encode()) <= 16000
            assert "input" in first["truncated_fields"]
        assert events[1]["usage"]["output_tokens"] == 3


def test_missing_token_and_collector_do_not_raise_to_the_caller(tmp_path):
    reporter = TraceReporter("unix:/missing", tmp_path / "missing-token", "fixture")
    try:
        reporter.span("run", "fixture").finish("success")
    finally:
        reporter.close(2)
    assert reporter.dropped_total == 2
    assert not reporter._worker.is_alive()
