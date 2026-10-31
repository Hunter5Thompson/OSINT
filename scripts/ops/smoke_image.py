"""Smoke an actual app image on an internal network, without production inputs."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import uuid

SERVICES = ("backend", "frontend", "intelligence", "data-ingestion")
MODEL_FIXTURE = """
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
models = ['smoke-base', 'smoke-synthesis']
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != '/v1/models':
            self.send_error(404)
            return
        body = json.dumps({'data': [{'id': m} for m in models]}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(body)
    def do_POST(self):
        models[:] = ['smoke-base']
        self.send_response(204)
        self.end_headers()
HTTPServer(('0.0.0.0', 8000), Handler).serve_forever()
"""


def docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    # DOCKER_HOST can select a separate /data-backed daemon for local checks.
    return subprocess.run(
        ["docker", *args], check=check, capture_output=True, text=True, timeout=60
    )


def wait_for_http(name: str, port: int, path: str, status: int, revision: str) -> dict:
    probe = f"""
import json
import urllib.request
from urllib.error import HTTPError
try:
    response = urllib.request.urlopen('http://127.0.0.1:{port}{path}', timeout=2)
except HTTPError as error:
    response = error
body = json.loads(response.read())
assert response.status == {status}, response.status
assert body['revision'] == {revision!r}, body
print(json.dumps(body))
"""
    deadline = time.monotonic() + 45
    last = ""
    while time.monotonic() < deadline:
        result = docker("exec", name, "python", "-c", probe, check=False)
        if result.returncode == 0:
            return json.loads(result.stdout)
        last = result.stderr
        time.sleep(0.5)
    raise RuntimeError(f"{name}: HTTP smoke timed out: {last[-1000:]}")


def json_response(name: str, path: str, status: int) -> dict:
    probe = f"""
import json
import urllib.request
from urllib.error import HTTPError
try:
    response = urllib.request.urlopen('http://127.0.0.1:8000{path}', timeout=2)
except HTTPError as error:
    response = error
assert response.status == {status}, response.status
print(response.read().decode())
"""
    response = docker("exec", name, "python", "-c", probe, check=False)
    if response.returncode != 0:
        raise RuntimeError(f"{name}: {path} expected HTTP {status}: {response.stderr}")
    return json.loads(response.stdout)


def smoke(service: str, image: str, revision: str) -> dict:
    config = json.loads(docker("image", "inspect", image).stdout)[0]
    image_revision = (config["Config"]["Labels"] or {}).get("org.opencontainers.image.revision")
    assert image_revision == revision, "image OCI revision does not match the expected checkout"
    image_id = config["Id"]
    prefix = f"odin-image-smoke-{uuid.uuid4().hex[:12]}"
    network = prefix + "-network"
    names = []
    docker("network", "create", "--internal", network)
    try:
        name = prefix + "-app"
        environment = [
            "ODIN_BUILD_REVISION=" + "b" * 40,
            "NEO4J_PASSWORD=image-smoke-test-only",
            "NEO4J_URL=bolt://127.0.0.1:1",
            "NEO4J_URI=bolt://127.0.0.1:1",
            "REDIS_URL=redis://127.0.0.1:1/0",
            "QDRANT_URL=http://127.0.0.1:1",
            "TEI_EMBED_URL=http://127.0.0.1:1",
            "TEI_RERANK_URL=http://127.0.0.1:1",
            "ODIN_PROMOTER_ENABLED=false",
        ]
        if service == "intelligence":
            fixture = prefix + "-models"
            docker(
                "run",
                "-d",
                "--name",
                fixture,
                "--network",
                network,
                "--network-alias",
                "smoke-models",
                "--entrypoint",
                "python",
                image_id,
                "-c",
                MODEL_FIXTURE,
            )
            names.append(fixture)
            environment += [
                "VLLM_URL=http://smoke-models:8000",
                "VLLM_MODEL=smoke-base",
                "SYNTHESIS_MODEL=smoke-synthesis",
            ]
        arguments = ["run", "-d", "--name", name, "--network", network]
        for value in environment:
            arguments += ["-e", value]
        docker(*arguments, image_id)  # Actual image CMD/entrypoint, no code binds or host ports.
        names.append(name)
        result: dict = {"service": service, "image_id": image_id, "revision": revision}
        if service == "backend":
            result["health"] = wait_for_http(name, 8000, "/api/health", 200, revision)
            result["optional_recon"] = json_response(name, "/api/recon/scenes", 200)
            assert result["optional_recon"] == {
                "scenes": [], "availability": "disabled", "reason": "not_configured",
            }
            configured_name = prefix + "-required-recon"
            configured_arguments = ["run", "-d", "--name", configured_name, "--network", network]
            for value in environment + ["RECON_MODE=enabled"]:
                configured_arguments += ["-e", value]
            docker(*configured_arguments, image_id)
            names.append(configured_name)
            result["required_recon_core"] = wait_for_http(
                configured_name, 8000, "/api/health", 200, revision,
            )
            result["required_recon_error"] = json_response(
                configured_name, "/api/recon/scenes", 503,
            )
        elif service == "intelligence":
            result["ready"] = wait_for_http(name, 80, "/health", 200, revision)
            assert result["ready"]["required_models"] == ["smoke-base", "smoke-synthesis"]
            docker(
                "exec",
                fixture,
                "python",
                "-c",
                "import urllib.request; urllib.request.urlopen("
                "urllib.request.Request('http://127.0.0.1:8000/missing', method='POST'))",
            )
            result["missing_model"] = wait_for_http(name, 80, "/health", 503, revision)
            assert result["missing_model"]["missing_models"] == ["smoke-synthesis"]
        elif service == "frontend":
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                response = docker(
                    "exec",
                    name,
                    "wget",
                    "-S",
                    "-O",
                    "-",
                    "http://127.0.0.1:5173/build-info.json",
                    check=False,
                )
                if response.returncode == 0:
                    break
                time.sleep(0.5)
            assert response.returncode == 0, response.stderr
            assert json.loads(response.stdout)["revision"] == revision
            assert "Content-Type: application/json" in response.stderr
            assert "Cache-Control: no-cache" in response.stderr
            page = docker("exec", name, "wget", "-qO-", "http://127.0.0.1:5173/")
            assert '<script type="module"' in page.stdout
            # Only this disposable container loses metadata; the image stays intact.
            docker("exec", name, "rm", "/usr/share/nginx/html/build-info.json")
            missing = docker(
                "exec",
                name,
                "wget",
                "-S",
                "-O",
                "-",
                "http://127.0.0.1:5173/build-info.json",
                check=False,
            )
            assert missing.returncode != 0 and "404 Not Found" in missing.stderr
            result["metadata_http"] = 200
            result["missing_metadata_http"] = 404
        else:
            deadline = time.monotonic() + 30
            starting = running = None
            while time.monotonic() < deadline:
                logs = docker("logs", name).stdout
                for line in logs.splitlines():
                    try:
                        entry = json.loads(line)
                    except ValueError:
                        continue
                    if entry.get("event") == "scheduler_starting":
                        starting = entry
                    elif entry.get("event") == "scheduler_running":
                        running = entry
                if running is not None:
                    break
                time.sleep(0.5)
            assert starting is not None and starting["revision"] == revision
            assert running is not None and running["revision"] == revision
            result["scheduler_revision"] = running["revision"]
        return result
    except Exception:
        for name in names:
            logs = docker("logs", "--tail", "20", name, check=False)
            print(logs.stdout + logs.stderr, file=sys.stderr)
        raise
    finally:
        for name in reversed(names):
            docker("rm", "-f", name, check=False)
        docker("network", "rm", network, check=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service", choices=SERVICES)
    parser.add_argument("image")
    parser.add_argument("revision")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.revision):
        parser.error("revision must be a full lowercase Git SHA")
    print(json.dumps(smoke(args.service, args.image, args.revision)))


if __name__ == "__main__":
    main()
