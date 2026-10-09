"""Dependency-free best-effort reporter for Spark Tracing Lite.

This standalone file can be mounted into clients. Its bounded background worker
keeps tracing off the inference path; callers may run entirely without a collector.
"""

from __future__ import annotations

import contextvars
import http.client
import json
import queue
import socket
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

CURRENT_SPAN = contextvars.ContextVar("spark_trace_span", default=None)
MAX_CONTENT = 65536


def utc_now():
    return datetime.now(UTC).isoformat()


def bounded_content(value, truncated, field):
    def scrub(item, depth=0):
        if depth > 12:
            truncated.append(field)
            return "[depth limit]"
        if isinstance(item, dict):
            result = {}
            for key, part in list(item.items())[:100]:
                key = str(key)
                if any(
                    word in key.lower()
                    for word in (
                        "password",
                        "api_key",
                        "authorization",
                        "access_token",
                        "secret",
                    )
                ):
                    result[key] = "[redacted]"
                else:
                    result[key] = scrub(part, depth + 1)
            return result
        if isinstance(item, (tuple, list)):
            return [scrub(part, depth + 1) for part in item[:100]]
        if isinstance(item, str):
            if item.startswith("data:") or (
                len(item) > 4096 and field in ("input", "output") and "base64," in item
            ):
                truncated.append(field)
                return "[binary content omitted]"
            if len(item.encode()) > 16000:
                truncated.append(field)
                return item.encode()[:16000].decode("utf-8", "ignore")
            return item
        if item is None or type(item) in (int, float, bool):
            return item
        if hasattr(item, "model_dump"):
            return scrub(item.model_dump(), depth + 1)
        return str(item)[:4000]

    result = scrub(value)
    encoded = json.dumps(result, ensure_ascii=False, allow_nan=False).encode()
    if len(encoded) > MAX_CONTENT:
        truncated.append(field)
        return encoded[:16000].decode("utf-8", "ignore")
    return result


class _UnixConnection(http.client.HTTPConnection):
    def __init__(self, path):
        super().__init__("localhost", timeout=0.5)
        self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


class TraceReporter:
    def __init__(
        self, endpoint, token_file, client_id, capture="metadata", project="odin"
    ):
        self.endpoint, self.client_id, self.capture, self.project = (
            endpoint,
            client_id,
            capture,
            project,
        )
        self.instance_id = uuid.uuid4().hex
        self.dropped_total = 0
        self.last_send_error = None
        self._queue = queue.Queue(maxsize=100)
        self._stop = threading.Event()
        self._closed = False
        self._lock = threading.Lock()
        try:
            self._token = Path(token_file).read_text().strip()
            if not self._token:
                raise ValueError("empty token")
        except (OSError, ValueError) as exc:
            self._token = ""
            self.last_send_error = type(exc).__name__
        self._worker = threading.Thread(
            target=self._run, name="spark-trace-reporter", daemon=True
        )
        self._worker.start()

    def emit(self, event):
        try:
            if self._closed:
                raise queue.Full
            copy = json.loads(json.dumps(event, allow_nan=False))
            truncated = list(copy.get("truncated_fields", []))
            for field in (
                "input",
                "output",
                "error",
                "metadata",
                "requested_parameters",
                "reported_parameters",
            ):
                if field in copy:
                    if field in ("input", "output") and self.capture != "text":
                        copy.pop(field)
                    else:
                        copy[field] = bounded_content(copy[field], truncated, field)
            copy["truncated_fields"] = sorted(set(truncated))
            copy["content_capture"] = self.capture
            self._queue.put_nowait(("/api/traces/events", copy))
            return True
        except Exception:
            with self._lock:
                self.dropped_total += 1
            return False

    def _send(self, path, value):
        if not self._token:
            raise ValueError("ingestion token unavailable")
        if self.endpoint.startswith("unix:"):
            connection = _UnixConnection(self.endpoint[5:])
        else:
            parts = urlsplit(self.endpoint)
            if parts.scheme != "http" or parts.hostname not in (
                "127.0.0.1",
                "localhost",
                "::1",
            ):
                raise ValueError("reporter endpoint must be local HTTP or Unix socket")
            connection = http.client.HTTPConnection(
                parts.hostname, parts.port or 80, timeout=0.5
            )
        try:
            connection.request(
                "POST",
                path,
                json.dumps(value, allow_nan=False).encode(),
                {
                    "Authorization": f"Bearer {self._token}",
                    "Content-Type": "application/json",
                },
            )
            response = connection.getresponse()
            response.read(1024)
            if response.status not in (200, 201):
                raise OSError(f"ingestion status {response.status}")
        finally:
            connection.close()

    def _run(self):
        health_at = 0
        while not self._stop.is_set() or not self._queue.empty():
            try:
                path, value = self._queue.get(timeout=0.1)
            except queue.Empty:
                path, value = None, None
            if path:
                sent = False
                for _ in range(2):
                    try:
                        self._send(path, value)
                        sent = True
                        self.last_send_error = None
                        break
                    except Exception as exc:
                        self.last_send_error = str(exc)[:256]
                if not sent:
                    with self._lock:
                        self.dropped_total += 1
                self._queue.task_done()
            if time.monotonic() - health_at >= 30:
                health_at = time.monotonic()
                try:
                    self._send(
                        "/api/traces/reporters",
                        dict(
                            client_id=self.client_id,
                            instance_id=self.instance_id,
                            observed_at=utc_now(),
                            dropped_total=self.dropped_total,
                            last_send_error=self.last_send_error,
                        ),
                    )
                except Exception as exc:
                    self.last_send_error = str(exc)[:256]

    def close(self, timeout=1.0):
        self._closed = True
        self._stop.set()
        self._worker.join(max(0, timeout))
        if self._worker.is_alive():
            while True:
                try:
                    self._queue.get_nowait()
                    self._queue.task_done()
                    self.dropped_total += 1
                except queue.Empty:
                    break

    def span(
        self,
        kind,
        name,
        *,
        trace_id=None,
        parent_span_id=None,
        target_id="workflow",
        spark_id=None,
        input=None,
        **fields,
    ):
        return TraceSpan(
            self,
            kind,
            name,
            trace_id,
            parent_span_id,
            target_id,
            spark_id,
            input,
            fields,
        )


class TraceSpan:
    def __init__(
        self,
        reporter,
        kind,
        name,
        trace_id,
        parent_span_id,
        target_id,
        spark_id,
        input,
        fields,
    ):
        self.reporter = reporter
        self.started = time.perf_counter()
        self.finished = False
        parent = CURRENT_SPAN.get()
        self.trace_id = trace_id or (parent.trace_id if parent else uuid.uuid4().hex)
        self.span_id = uuid.uuid4().hex
        self.base = dict(
            schema_version=1,
            trace_id=self.trace_id,
            span_id=self.span_id,
            parent_span_id=parent_span_id
            if parent_span_id
            else (parent.span_id if parent else None),
            project=reporter.project,
            client_id=reporter.client_id,
            target_id=target_id,
            spark_id=spark_id,
            kind=kind,
            name=name,
        )
        observed_at = fields.pop("observed_at", utc_now())
        self.reporter.emit(
            dict(
                self.base,
                event_id=uuid.uuid4().hex,
                event_type="start",
                observed_at=observed_at,
                input=input,
                **fields,
            )
        )
        self._context_token = None

    def __enter__(self):
        self._context_token = CURRENT_SPAN.set(self)
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._context_token is not None:
            CURRENT_SPAN.reset(self._context_token)
        if not self.finished:
            self.finish(
                "cancelled"
                if exc_type and exc_type.__name__ == "CancelledError"
                else "error"
                if exc
                else "success",
                **(
                    {"error": {"type": exc_type.__name__, "message": str(exc)[:4000]}}
                    if exc
                    else {}
                ),
            )

    async def __aenter__(self):
        return self.__enter__()

    async def __aexit__(self, *args):
        self.__exit__(*args)

    def finish(self, status="success", **fields):
        if self.finished:
            return
        self.finished = True
        fields.setdefault("duration_ms", (time.perf_counter() - self.started) * 1000)
        self.reporter.emit(
            dict(
                self.base,
                event_id=uuid.uuid4().hex,
                event_type="finish",
                observed_at=utc_now(),
                status=status,
                **fields,
            )
        )
