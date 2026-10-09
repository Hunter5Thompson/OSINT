"""Probe baked tracing through a disposable Unix collector; no providers or production inputs."""

from __future__ import annotations

import argparse
import json
import re
import socket
import sys
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from smoke_image import docker

PROBE = r'''
import asyncio, json, os, time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from build_revision import BUILD_REVISION
import tracing
assert BUILD_REVISION == os.environ['EXPECTED_REVISION'], BUILD_REVISION
service = os.environ['SMOKE_SERVICE']

async def invoke():
    if service == 'intelligence':
        from graph import workflow
        async def create(**request):
            return SimpleNamespace(model_dump=lambda: {
                'model': 'trace-smoke', 'usage': {'prompt_tokens': 8, 'completion_tokens': 2},
                'choices': [{'message': {'content': 'fixture'}, 'finish_reason': 'stop'}],
            })
        async def graph(state, **kwargs):
            await tracing.trace_completion(create, model='trace-smoke', messages=[])
            return {'synthesis': 'fixture result'}
        with patch.object(workflow, '_ensure_graph_client'), patch.object(
            workflow, 'react_graph', SimpleNamespace(ainvoke=graph)
        ):
            result = await workflow.run_intelligence_query('isolated trace fixture')
        assert result['analysis'] == 'fixture result', result
    else:
        import httpx
        from config import settings
        from pipeline import _call_vllm
        def provider(request):
            assert json.loads(request.content)['max_tokens'] == 2000
            return httpx.Response(200, json={
                'model': 'trace-smoke', 'usage': {'prompt_tokens': 8, 'completion_tokens': 2},
                'choices': [{'message': {'content': '{}'}, 'finish_reason': 'stop'}],
            })
        client_class = httpx.AsyncClient
        with patch('pipeline.httpx.AsyncClient', side_effect=lambda **kw: client_class(
            transport=httpx.MockTransport(provider), **kw
        )):
            assert await _call_vllm('fixture', 'body', 'https://source.test', settings) == {}

async def main():
    reporter = tracing.get_reporter()
    assert reporter is not None, 'baked reporter must load'
    instance = reporter.instance_id
    try:
        for phase in (1, 2, 3):
            if phase > 1:
                deadline = time.monotonic() + 25
                while not Path(f'/run/spark-tracing/request-{phase}').exists():
                    assert time.monotonic() < deadline, 'control phase timed out'
                    await asyncio.sleep(0.1)
            previous = reporter.dropped_total
            await invoke()
            deadline = time.monotonic() + 15
            while reporter._queue.unfinished_tasks:
                assert time.monotonic() < deadline, 'trace worker did not drain'
                await asyncio.sleep(0.05)
            dropped = reporter.dropped_total - previous
            assert dropped > 0 if phase == 2 else dropped == 0, (phase, dropped)
            assert reporter.instance_id == instance
            print(json.dumps({'phase': phase, 'status': 'ok', 'dropped': dropped,
                              'instance': instance}), flush=True)
    finally:
        await asyncio.to_thread(tracing.close_reporter)

asyncio.run(main())
'''


class UnixServer(HTTPServer):
    address_family = socket.AF_UNIX


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        if self.headers.get("Authorization") != "Bearer fixture-only":
            self.send_error(401)
            return
        body = self.rfile.read(int(self.headers["Content-Length"]))
        event = json.loads(body)
        if self.server.canonical_api is not None:
            status, _result = self.server.canonical_api.dispatch(
                "POST", self.path, self.headers, body,
            )
            if status not in (200, 201):
                self.send_error(status)
                return
        if self.path == "/api/traces/events":
            assert event["schema_version"] == 1
            assert event["event_type"] in ("start", "finish")
            assert event["kind"] in ("run", "generation")
            assert event["content_capture"] == "metadata"
            assert "input" not in event and "output" not in event
            if event["event_type"] == "finish":
                assert event["status"] == "success"
            self.server.events.append(event)
        elif self.path == "/api/traces/reporters":
            assert event["client_id"] in ("odin-intelligence", "odin-ingestion")
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{}')

    def log_message(self, *_args: object) -> None:
        pass


def start_collector(
    path: Path, events: list[dict], canonical_api=None,
) -> tuple[UnixServer, threading.Thread]:
    server = UnixServer(str(path), Handler)
    server.events = events
    server.canonical_api = canonical_api
    path.chmod(0o600)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    return server, worker


def stop_collector(server: UnixServer, worker: threading.Thread, path: Path) -> None:
    server.shutdown()
    server.server_close()
    worker.join(2)
    path.unlink(missing_ok=True)


def wait_phase(name: str, phase: int) -> dict:
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        logs = docker("logs", name)
        for line in logs.stdout.splitlines():
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if entry.get("phase") == phase:
                return entry
        state = json.loads(docker("inspect", "--format", "{{json .State}}", name).stdout)
        if not state["Running"]:
            raise RuntimeError(
                f"trace probe exited {state['ExitCode']}: {logs.stdout}{logs.stderr}"
            )
        time.sleep(0.2)
    raise RuntimeError("trace probe phase timed out")


def smoke(
    service: str, image: str, revision: str, work_dir: str | None,
    collector_source: str | None = None,
) -> dict:
    config = json.loads(docker("image", "inspect", image).stdout)[0]
    assert config["Config"]["Labels"]["org.opencontainers.image.revision"] == revision
    name = "odin-trace-smoke-" + uuid.uuid4().hex[:12]
    with tempfile.TemporaryDirectory(prefix="odin-trace-", dir=work_dir) as root:
        directory = Path(root)
        run_directory = directory / "run"
        run_directory.mkdir()
        socket_path = run_directory / "ingest.sock"
        token = directory / "token"
        token.write_text("fixture-only")
        token.chmod(0o600)
        events = []
        canonical_api = store = None
        if collector_source is not None:
            sys.path.insert(0, str(Path(collector_source).resolve()))
            from spark_widget.trace_api import TraceApi
            from spark_widget.trace_store import TraceStore

            store = TraceStore(directory / "collector-data")
            canonical_api = TraceApi(store, "fixture-only")
        server, worker = start_collector(socket_path, events, canonical_api)
        try:
            environment = {
                "SMOKE_SERVICE": service, "EXPECTED_REVISION": revision,
                "SPARK_TRACE_ENDPOINT": "unix:/run/spark-tracing/ingest.sock",
                "SPARK_TRACE_TOKEN_FILE": "/run/spark-tracing-token",
                "SPARK_TRACE_CAPTURE": "metadata",
                "SPARK_TRACE_TARGET_ID": "spark" if service == "data-ingestion"
                    else "workstation-5090",
                "SPARK_TRACE_SPARK_ID": "spark" if service == "data-ingestion" else "",
            }
            arguments = ["run", "-d", "--name", name, "--network", "none", "--mount",
                         f"type=bind,source={run_directory},target=/run/spark-tracing,readonly",
                         "--mount",
                         f"type=bind,source={token},target=/run/spark-tracing-token,readonly"]
            for key, value in environment.items():
                arguments += ["-e", f"{key}={value}"]
            docker(*arguments, "--entrypoint", "python", config["Id"], "-u", "-c", PROBE)
            phases = [wait_phase(name, 1)]
            stop_collector(server, worker, socket_path)
            server = None
            (run_directory / "request-2").touch()
            phases.append(wait_phase(name, 2))
            server, worker = start_collector(socket_path, events, canonical_api)
            (run_directory / "request-3").touch()
            phases.append(wait_phase(name, 3))
            assert phases[0]["instance"] == phases[1]["instance"] == phases[2]["instance"]
            finished = [event for event in events if event["event_type"] == "finish"]
            assert len(finished) == 4
            generations = [event for event in finished if event["kind"] == "generation"]
            assert len(generations) == 2
            assert all(event["usage"]["input_tokens"] == 8 for event in generations)
            assert all(event["ttft_ms"] is None for event in generations)
            if store is not None:
                traces = store.list_traces({}, 10, None)["items"]
                assert len(traces) == 2
                assert all(trace["status"] == "success" for trace in traces)
            return {"service": service, "image_id": config["Id"], "revision": revision,
                    "phases": phases, "online_finished_spans": len(finished),
                    "collector": "canonical collector API/schema/store on disposable data"
                        if store is not None else "isolated schema-v1 protocol fixture",
                    "network": "none"}
        finally:
            docker("rm", "-f", name, check=False)
            if server is not None:
                stop_collector(server, worker, socket_path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service", choices=("intelligence", "data-ingestion"))
    parser.add_argument("image")
    parser.add_argument("revision")
    parser.add_argument("--work-dir")
    parser.add_argument("--collector-source", help="Optional local canonical collector source")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.revision):
        parser.error("revision must be a full lowercase Git SHA")
    print(json.dumps(smoke(args.service, args.image, args.revision, args.work_dir,
                          args.collector_source)))


if __name__ == "__main__":
    main()
