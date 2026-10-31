"""Operator gateway is an explicit, baked release option with runtime secrets."""

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_gateway_is_baked_and_has_no_build_time_credential():
    dockerfile = (ROOT / "services/frontend/Dockerfile").read_text()
    assert "COPY operator-gateway/ /opt/odin/operator-gateway/" in dockerfile
    assert "COPY docker-entrypoint.d/ /docker-entrypoint.d/" in dockerfile
    assert "ARG ODIN_OPERATOR_TOKEN" not in dockerfile
    assert "ENV ODIN_OPERATOR_TOKEN" not in dockerfile
    assert (
        "include /etc/nginx/operator-gateway/*.conf;"
        in (ROOT / "services/frontend/nginx.conf").read_text()
    )


def test_gateway_overlay_is_loopback_only_and_uses_a_runtime_secret():
    env = {
        "PATH": os.environ["PATH"],
        "ODIN_BIND_HOST": "0.0.0.0",
        "ODIN_OPERATOR_TOKEN_FILE": "/data/test-only-operator-token",
    }
    env.update(
        {
            name: "odin/test@sha256:" + "a" * 64
            for name in (
                "ODIN_BACKEND_IMAGE",
                "ODIN_FRONTEND_IMAGE",
                "ODIN_INTELLIGENCE_IMAGE",
                "ODIN_INGESTION_IMAGE",
                "ODIN_VISION_IMAGE",
                "ODIN_RERANK_IMAGE",
            )
        }
    )
    env["ODIN_RELEASE_DATA_DIR"] = "/data/test-only-release"
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            "tests/fixtures/compose.env",
            "-f",
            "docker-compose.yml",
            "-f",
            "docker-compose.override.yml",
            "-f",
            "docker-compose.release.yml",
            "-f",
            "docker-compose.operator-gateway.yml",
            "--profile",
            "*",
            "config",
            "--format",
            "json",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    config = json.loads(result.stdout)
    frontend = config["services"]["frontend"]
    assert frontend["ports"] == [
        {
            "mode": "ingress",
            "host_ip": "127.0.0.1",
            "target": 5173,
            "published": "5173",
            "protocol": "tcp",
        }
    ]
    assert frontend["environment"]["ODIN_OPERATOR_GATEWAY_ENABLED"] == "true"
    assert frontend["secrets"] == [
        {"source": "odin_operator_token", "target": "/run/secrets/odin_operator_token"}
    ]
    assert config["secrets"]["odin_operator_token"]["file"] == env["ODIN_OPERATOR_TOKEN_FILE"]
    assert "build" not in frontend
    assert not frontend.get("volumes")


def test_gateway_requires_explicit_release_mode():
    result = subprocess.run(
        ["bash", "odin.sh", "--operator-gateway", "ps"], cwd=ROOT, capture_output=True, text=True
    )
    assert result.returncode == 2
    assert "--operator-gateway requires --release" in result.stdout


def test_odin_passes_gateway_overlay_after_release(tmp_path):
    docker = tmp_path / "docker"
    docker.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
    docker.chmod(0o755)
    result = subprocess.run(
        [
            "bash",
            "odin.sh",
            "--env-file",
            "tests/fixtures/compose.env",
            "--release",
            "--operator-gateway",
            "ps",
        ],
        cwd=ROOT,
        env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=True,
    )
    args = result.stdout.splitlines()
    assert args.index("docker-compose.release.yml") < args.index(
        "docker-compose.operator-gateway.yml"
    )
    assert args[-1] == "ps"
