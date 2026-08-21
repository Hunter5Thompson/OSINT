"""Executable contract for ODIN's local-only host exposure floor."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FIXTURE = ROOT / "tests" / "fixtures" / "compose.env"
PROFILES = ("interactive", "ingestion", "interactive-spark", "notebooklm", "vision")
PUBLISHED_PORTS = {
    "backend": {"8080"},
    "frontend": {"5173"},
    "intelligence": {"8003"},
    "neo4j": {"7474", "7687"},
    "qdrant": {"6333", "6334"},
    "redis": {"6379"},
    "tei-embed": {"8001"},
    "tei-rerank": {"8002"},
    "vllm-27b": {"8000"},
    "vllm-9b": {"8000"},
    "vllm-vision": {"8011"},
    "vllm-voxtral": {"8010"},
}


def _copy_compose_project(destination: Path, fixture_text: str | None = None) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "docker-compose.yml", destination / "docker-compose.yml")
    shutil.copy2(
        ROOT / "docker-compose.override.yml",
        destination / "docker-compose.override.yml",
    )
    fixture = destination / "tests" / "fixtures" / "compose.env"
    fixture.parent.mkdir(parents=True)
    if fixture_text is None:
        shutil.copy2(COMPOSE_FIXTURE, fixture)
    else:
        fixture.write_text(fixture_text, encoding="utf-8")
    return fixture


def _compose_result(
    project: Path,
    *,
    bind_host: str | None = None,
    fixture_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    fixture = _copy_compose_project(project, fixture_text)
    home = project / "home"
    home.mkdir()
    env = {
        "HOME": str(home),
        "ODIN_ENV_FILE": str(fixture.relative_to(project)),
        "PATH": os.environ["PATH"],
    }
    if bind_host is not None:
        env["ODIN_BIND_HOST"] = bind_host

    command = [
        "docker",
        "compose",
        "--env-file",
        str(fixture.relative_to(project)),
    ]
    for profile in PROFILES:
        command.extend(("--profile", profile))
    command.extend(("config", "--no-env-resolution", "--format", "json"))
    result = subprocess.run(
        command,
        cwd=project,
        env=env,
        check=False,
        text=True,
        capture_output=True,
    )
    assert not (project / ".env").exists()
    return result


def _render(
    project: Path,
    *,
    bind_host: str | None = None,
) -> dict:
    result = _compose_result(project, bind_host=bind_host)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _published_ports(config: dict) -> dict[str, set[str]]:
    return {
        service_name: {port["published"] for port in service["ports"]}
        for service_name, service in config["services"].items()
        if service.get("ports")
    }


def _assert_host_ip(config: dict, expected: str) -> None:
    assert _published_ports(config) == PUBLISHED_PORTS
    for service_name in PUBLISHED_PORTS:
        for port in config["services"][service_name]["ports"]:
            assert port.get("host_ip") == expected, (service_name, port)


def _doctor(
    tmp_path: Path,
    secret_file: Path,
    bind_host: str,
    *,
    script: Path = ROOT / "odin.sh",
) -> subprocess.CompletedProcess[str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    for command in ("docker", "curl", "uv"):
        executable = fake_bin / command
        executable.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)

    env = {
        "HOME": str(tmp_path / "home"),
        "MODELS_PATH": str(tmp_path / "models"),
        "NEO4J_PASSWORD": "compose-test-only",
        "ODIN_BIND_HOST": bind_host,
        "ODIN_ENV_FILE": str(secret_file),
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "SPARK_VLLM_URL": "http://127.0.0.1:1",
    }
    return subprocess.run(
        [str(script), "doctor", str(secret_file)],
        cwd=script.parent,
        env=env,
        check=False,
        text=True,
        capture_output=True,
    )


def test_all_published_ports_default_to_ipv4_loopback(tmp_path: Path) -> None:
    config = _render(tmp_path)

    _assert_host_ip(config, "127.0.0.1")


def test_explicit_non_loopback_host_renders_but_doctor_rejects_it(tmp_path: Path) -> None:
    bind_host = "192.0.2.10"
    config = _render(tmp_path / "compose", bind_host=bind_host)
    _assert_host_ip(config, bind_host)

    secret_file = tmp_path / "doctor.env"
    secret_file.write_text("NEO4J_PASSWORD=must-not-be-printed\n", encoding="utf-8")
    secret_file.chmod(0o600)
    result = _doctor(tmp_path / "doctor", secret_file, bind_host)

    assert result.returncode != 0
    assert "unauthenticated services" in result.stdout
    assert "ODIN_BIND_HOST=192.0.2.10" in result.stdout
    assert "must-not-be-printed" not in result.stdout + result.stderr


def test_compose_requires_neo4j_password_without_fallback(tmp_path: Path) -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    required = "${NEO4J_PASSWORD:?NEO4J_PASSWORD is required}"
    assert compose.count(required) == 5
    assert "NEO4J_PASSWORD:-" not in compose
    assert "odin1234" not in compose

    without_password = "\n".join(
        line
        for line in COMPOSE_FIXTURE.read_text(encoding="utf-8").splitlines()
        if not line.startswith("NEO4J_PASSWORD=")
    )
    result = _compose_result(tmp_path, fixture_text=f"{without_password}\n")

    assert result.returncode != 0
    assert "NEO4J_PASSWORD is required" in result.stderr


def test_doctor_rejects_group_readable_secret_and_accepts_mode_600(
    tmp_path: Path,
) -> None:
    secret_file = tmp_path / "doctor.env"
    secret_value = "must-not-be-printed"
    secret_file.write_text(f"NEO4J_PASSWORD={secret_value}\n", encoding="utf-8")
    secret_file.chmod(0o640)

    unsafe = _doctor(tmp_path / "unsafe", secret_file, "127.0.0.1")
    assert unsafe.returncode != 0
    assert str(secret_file) in unsafe.stdout
    assert "expected mode 600 or stricter" in unsafe.stdout
    assert secret_value not in unsafe.stdout + unsafe.stderr

    secret_file.chmod(0o600)
    safe = _doctor(tmp_path / "safe", secret_file, "127.0.0.1")
    assert safe.returncode == 0, safe.stdout + safe.stderr
    assert secret_value not in safe.stdout + safe.stderr


def test_doctor_checks_nested_repository_env_files(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    (repository / "services" / "data-ingestion").mkdir(parents=True)
    nested = repository / "services" / "backend" / ".env"
    nested.parent.mkdir(parents=True)
    nested.write_text("NESTED_SECRET=must-not-be-printed\n", encoding="utf-8")
    nested.chmod(0o644)
    primary = repository / ".env"
    primary.write_text("NEO4J_PASSWORD=must-not-be-printed\n", encoding="utf-8")
    primary.chmod(0o600)
    script = repository / "odin.sh"
    shutil.copy2(ROOT / "odin.sh", script)

    unsafe = _doctor(
        tmp_path / "unsafe-nested",
        primary,
        "127.0.0.1",
        script=script,
    )
    assert unsafe.returncode != 0
    assert str(nested) in unsafe.stdout
    assert "must-not-be-printed" not in unsafe.stdout + unsafe.stderr

    nested.chmod(0o600)
    safe = _doctor(
        tmp_path / "safe-nested",
        primary,
        "127.0.0.1",
        script=script,
    )
    assert safe.returncode == 0, safe.stdout + safe.stderr


def test_examples_and_registry_contain_no_weak_neo4j_default() -> None:
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    tasks = (ROOT / "TASKS.md").read_text(encoding="utf-8")

    assert "NEO4J_PASSWORD=\n" in env_example
    assert "NEO4J_PASSWORD=odin1234" not in env_example
    assert "odin_yggdrasil" not in tasks


def test_container_connections_keep_compose_dns(tmp_path: Path) -> None:
    services = _render(tmp_path)["services"]

    assert services["backend"]["environment"]["REDIS_URL"] == "redis://redis:6379/0"
    assert services["backend"]["environment"]["QDRANT_URL"] == "http://qdrant:6333"
    assert services["backend"]["environment"]["NEO4J_URL"] == "bolt://neo4j:7687"
    assert services["intelligence"]["environment"]["VLLM_URL"] == "http://vllm:8000"
