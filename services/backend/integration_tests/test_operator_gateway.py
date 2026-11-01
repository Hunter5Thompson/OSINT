"""Real nginx -> real backend routes -> isolated store and intelligence fakes.

Run explicitly from services/backend; requires Docker and the frontend's pinned
nginx image. Only the test-owned container and ephemeral loopback ports are used.
"""

import asyncio
import os
import re
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[3]
FRONTEND = ROOT / "services/frontend"
TOKEN = "test-only-operator-" + "x" * 40


def docker(*args, check=True):
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=check)


@pytest.fixture
def adapter(monkeypatch, tmp_path):
    # No lifespan, schema initialization, background feeds or production stores.
    monkeypatch.setenv("NEO4J_PASSWORD", "test-only-gateway")
    from app.config import settings
    from app.models.report import ReportMessage, ReportRecord
    from app.routers import almanac, intel, reports
    from app.services import report_store
    from app.services.spatial_catalog import CatalogReadyState, SpatialCatalogLoader

    monkeypatch.setattr(settings, "reports_admin_token", TOKEN)
    monkeypatch.setattr(settings, "incidents_admin_token", "")
    monkeypatch.setattr(settings, "model_admission_dir", tmp_path / "admission")
    loader = SpatialCatalogLoader(ROOT / "services/backend/data/spatial")
    state = asyncio.run(loader.load())
    assert isinstance(state, CatalogReadyState)
    application = FastAPI()
    application.state.report_schema_ready = True
    application.state.spatial_catalog = loader
    application.include_router(intel.router, prefix="/api")
    application.include_router(almanac.router, prefix="/api")
    application.include_router(reports.router, prefix="/api")
    report = ReportRecord(id="r-probe", paragraph_num=1, stamp="31·X", title="Gateway dossier")
    messages = []

    async def append_message(report_id, payload):
        message = ReportMessage(id=f"m-{len(messages)}", **payload.model_dump(exclude_none=True))
        messages.append(message)
        return message

    stores = {}
    for name, value in {
        "get_report": report,
        "list_reports": [report],
        "list_report_messages": messages,
        "update_report": report,
        "create_report": report,
        "delete_report": True,
        "get_or_create_report_by_scope": report,
    }.items():
        stores[name] = AsyncMock(return_value=value)
        monkeypatch.setattr(report_store, name, stores[name])
    append = AsyncMock(side_effect=append_message)
    monkeypatch.setattr(report_store, "append_report_message", append)
    # Almanac imports these functions explicitly.
    for name in ("update_report", "get_or_create_report_by_scope"):
        monkeypatch.setattr(almanac, name, stores[name])
    monkeypatch.setattr(almanac, "append_report_message", append)
    model = AsyncMock(
        return_value=httpx.Response(
            200,
            json={"analysis": "Gateway fake answer", "confidence": 0.8,
                  "sources_used": ["https://example.test/reviewed-source"]},
            request=httpx.Request("POST", "http://intelligence.test/query"),
        )
    )
    monkeypatch.setattr(httpx.AsyncClient, "post", model)

    @application.api_route("/{path:path}", methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"])
    async def probe(request: Request, path: str):
        return {
            "path": request.url.path,
            "credential_present": bool(request.headers.get("X-Admin-Token")),
        }

    receipts = []
    client = TestClient(application)

    class Handler(BaseHTTPRequestHandler):
        def forward(self):
            content = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            receipts.append(
                {
                    "path": self.path,
                    "credential_present": bool(self.headers.get("X-Admin-Token")),
                    "body": content,
                }
            )
            response = client.request(
                self.command, self.path, content=content, headers=dict(self.headers)
            )
            self.send_response(response.status_code)
            self.send_header(
                "Content-Type", response.headers.get("content-type", "application/json")
            )
            self.send_header("Content-Length", str(len(response.content)))
            self.end_headers()
            self.wfile.write(response.content)

        do_GET = do_POST = do_PATCH = do_DELETE = do_OPTIONS = forward  # noqa: N815

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield {
            "port": server.server_port,
            "revision": state.active_catalog_revision,
            "receipts": receipts,
            "model": model,
            "messages": messages,
            "stores": stores,
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        client.close()


@pytest.fixture
def gateway(tmp_path, adapter):
    # Ask the OS for a free port. Nginx binds only loopback on the host network.
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    config = (FRONTEND / "nginx.conf").read_text()
    config = config.replace("listen 5173;", f"listen 127.0.0.1:{port};")
    config = config.replace("http://backend:8000", f"http://127.0.0.1:{adapter['port']}")
    (tmp_path / "nginx.conf").write_text(config)
    templates = tmp_path / "templates"
    templates.mkdir()
    for source in (FRONTEND / "operator-gateway").iterdir():
        templates.joinpath(source.name).write_text(
            source.read_text().replace("http://backend:8000", f"http://127.0.0.1:{adapter['port']}")
        )
    secret = tmp_path / "token"
    secret.write_text(f" {TOKEN} \n")
    static = Path(os.environ.get("ODIN_GATEWAY_STATIC_ROOT", str(tmp_path / "static"))).resolve()
    if not static.exists():
        (static / "assets").mkdir(parents=True)
        (static / "index.html").write_text("<html>Gateway fixture</html>")
        (static / "assets/test.js").write_text("console.log('no credentials');")
    image = re.search(r"FROM (nginx:\S+)", (FRONTEND / "Dockerfile").read_text()).group(1)
    name = "odin-bp01-test-" + uuid.uuid4().hex[:12]
    mounts = [
        (tmp_path / "nginx.conf", "/etc/nginx/conf.d/default.conf"),
        (templates, "/opt/odin/operator-gateway"),
        (
            FRONTEND / "docker-entrypoint.d/40-odin-operator-gateway.sh",
            "/docker-entrypoint.d/40-odin-operator-gateway.sh",
        ),
        (secret, "/run/secrets/odin_operator_token"),
        (static, "/usr/share/nginx/html"),
    ]
    args = [
        "run",
        "-d",
        "--name",
        name,
        "--network",
        "host",
        "-e",
        "ODIN_OPERATOR_GATEWAY_ENABLED=true",
    ]
    for source, target in mounts:
        args += ["--mount", f"type=bind,src={source},dst={target},readonly"]
    try:
        docker(*args, image)
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}", timeout=5, trust_env=False
        ) as client:
            for _ in range(50):
                try:
                    if client.get("/").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            else:
                pytest.fail("nginx did not start: " + docker("logs", name).stdout)
            yield {
                **adapter,
                "client": client,
                "origin": f"http://127.0.0.1:{port}",
                "static": static,
                "name": name,
                "secret": secret,
            }
    finally:
        docker("rm", "-f", name, check=False)


def triggers(gateway):
    return [
        ("/api/intel/query", {"query": "global"}),
        (
            "/api/intel/query",
            {"query": "dossier", "report_id": "r-probe", "report_message": "question"},
        ),
        ("/api/intel/hotspot/ukr-001", None),
        ("/api/almanac/countries/UKR/briefing", None),
        (
            "/api/almanac/country/briefing?scope_key=country:UKR&catalog_revision="
            + gateway["revision"],
            None,
        ),
    ]


def test_gateway_routes_and_credentials(gateway):
    client = gateway["client"]
    for path, payload in triggers(gateway):
        response = client.post(
            path,
            json=payload,
            headers={"Origin": gateway["origin"], "Sec-Fetch-Site": "same-origin"},
        )
        assert response.status_code == 200, response.text
        assert "Gateway fake answer" in response.text
    assert gateway["model"].await_count == 5
    assert [message.role for message in gateway["messages"]] == ["user", "munin"]
    # Existing dossier CRUD, messages, and both briefing save aliases still work.
    for method, path, payload in [
        ("POST", "/api/reports", {"title": "test"}),
        ("PATCH", "/api/reports/r-probe", {"title": "patched"}),
        ("POST", "/api/reports/r-probe/messages", {"role": "user", "text": "test"}),
        ("DELETE", "/api/reports/r-probe", None),
        (
            "POST",
            "/api/almanac/countries/UKR/briefing/save",
            {"analysis": {"query": "q", "analysis": "saved"}},
        ),
        (
            "POST",
            "/api/almanac/country/briefing/save?scope_key=country:UKR&catalog_revision="
            + gateway["revision"],
            {"analysis": {"query": "q", "analysis": "saved"}},
        ),
    ]:
        # Saves check schema readiness; this flag belongs only to the fixture app.
        response = client.request(method, path, json=payload)
        assert response.status_code in (200, 201, 204), response.text
    for path in (
        "/api/reports",
        "/api/intel/history",
        "/api/intel/query/extra",
        "/api/incidents/_admin/trigger",
    ):
        method = "POST" if "extra" in path or "_admin" in path else "GET"
        client.request(method, path)
        assert gateway["receipts"][-1]["credential_present"] is False
    for method in ("GET", "PATCH", "DELETE", "OPTIONS"):
        client.request(method, "/api/intel/query")
        assert gateway["receipts"][-1]["credential_present"] is False


def test_gateway_rejects_cross_origin_before_backend_and_keeps_wrong_credentials(gateway):
    client = gateway["client"]
    for path, payload in triggers(gateway) + [("/api/reports", {})]:
        for headers in [
            {"Origin": "https://foreign.invalid"},
            {"Origin": "null"},
            {"Origin": gateway["origin"].replace("http:", "https:")},
            {"Sec-Fetch-Site": "cross-site"},
            {"Origin": gateway["origin"], "Sec-Fetch-Site": "cross-site"},
        ]:
            before = len(gateway["receipts"])
            assert client.post(path, json=payload, headers=headers).status_code == 403
            assert len(gateway["receipts"]) == before
        before = gateway["model"].await_count
        assert (
            client.post(path, json=payload, headers={"X-Admin-Token": "wrong"}).status_code == 401
        )
        assert gateway["model"].await_count == before
    assert gateway["messages"] == []
    for store in gateway["stores"].values():
        store.assert_not_awaited()
    # Missing Origin is deliberately allowed for local operator tools.
    assert client.post("/api/intel/query", json={"query": "local"}).status_code == 200
    # nginx treats an empty credential header like an absent credential.
    assert (
        client.post(
            "/api/intel/query",
            json={"query": "local"},
            headers={"X-Admin-Token": ""},
        ).status_code
        == 200
    )


def test_gateway_disabled_and_invalid_secret_fail_closed(gateway):
    name = gateway["name"]
    script = "/docker-entrypoint.d/40-odin-operator-gateway.sh"
    # Validate startup behavior in the test-owned container, never a live frontend.
    gateway["secret"].write_text('unsafe"; nginx injection')
    result = docker("exec", name, script, check=False)
    assert result.returncode != 0
    assert "unsafe" not in result.stderr
    result = docker("exec", "-e", "ODIN_OPERATOR_TOKEN_FILE=/missing", name, script, check=False)
    assert result.returncode != 0
    docker("exec", "-e", "ODIN_OPERATOR_GATEWAY_ENABLED=false", name, script)
    docker("exec", name, "nginx", "-s", "reload")
    # nginx reload is asynchronous; poll until the old worker exits.
    for _ in range(50):
        response = gateway["client"].post("/api/intel/query", json={"query": "disabled"})
        if response.status_code == 401:
            break
        time.sleep(0.1)
    assert response.status_code == 401


def test_runtime_token_is_absent_from_static_files_and_responses(gateway):
    token = TOKEN.encode()
    for path in gateway["static"].rglob("*"):
        if path.is_file():
            assert token not in path.read_bytes(), path
    for path in (
        "/",
        "/run/secrets/odin_operator_token",
        "/etc/nginx/conf.d/10-odin-operator-maps.conf",
    ):
        assert token not in gateway["client"].get(path).content


def test_built_dossier_chat_through_gateway(gateway):
    assert os.environ.get("ODIN_GATEWAY_STATIC_ROOT"), (
        "Build frontend and set ODIN_GATEWAY_STATIC_ROOT"
    )
    result = subprocess.run(
        ["node", "scripts/test-operator-gateway.mjs"],
        cwd=FRONTEND,
        env={**os.environ, "ODIN_GATEWAY_TEST_ORIGIN": gateway["origin"]},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert gateway["model"].await_count == 1
    assert [message.role for message in gateway["messages"]] == ["user", "munin"]
