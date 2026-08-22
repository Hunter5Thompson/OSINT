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


def _copy_odin_repository(destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "services" / "data-ingestion").mkdir(parents=True)
    for name in ("odin.sh", "docker-compose.yml", "docker-compose.override.yml"):
        shutil.copy2(ROOT / name, destination / name)
    return destination / "odin.sh"


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
    *,
    script: Path,
    shell_bind_host: str | None = None,
) -> subprocess.CompletedProcess[str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    for command in ("curl", "uv"):
        executable = fake_bin / command
        executable.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)

    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {
        "HOME": str(home),
        "MODELS_PATH": str(tmp_path / "models"),
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "SPARK_VLLM_URL": "http://127.0.0.1:1",
    }
    if shell_bind_host is not None:
        env["ODIN_BIND_HOST"] = shell_bind_host
    return subprocess.run(
        [str(script), "--env-file", str(secret_file), "doctor"],
        cwd=script.parent,
        env=env,
        check=False,
        text=True,
        capture_output=True,
    )


def _run_odin_with_fake_compose(
    repository: Path,
    runtime_dir: Path,
    arguments: list[str],
    *,
    preflight_bind_host: str = "127.0.0.1",
    preflight_secret_configured: bool = False,
) -> tuple[subprocess.CompletedProcess[str], str]:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    fake_bin = runtime_dir / "bin"
    fake_bin.mkdir(exist_ok=True)
    log_file = runtime_dir / "docker.log"
    docker = fake_bin / "docker"
    docker.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
{
  printf 'NEO4J_PASSWORD=%s\\n' "${NEO4J_PASSWORD:-<unset>}"
  printf 'ODIN_ENV_FILE=%s\\n' "${ODIN_ENV_FILE:-<unset>}"
  printf 'ARGS='
  printf '%q ' "$@"
  printf '\\n---\\n'
} >> "$ODIN_TEST_DOCKER_LOG"
if [[ " $* " == *" -f - config --format json "* ]]; then
  printf '{"services":{"odin-preflight":{'
  printf '"environment":{"NEO4J_CONFIGURED":"%s"},' \
    "$ODIN_TEST_PREFLIGHT_CONFIGURED"
  printf '"ports":[{"host_ip":"%s"}]}}}\\n' \
    "$ODIN_TEST_PREFLIGHT_BIND_HOST"
fi
exit 0
""",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    for command in ("curl", "uv"):
        executable = fake_bin / command
        executable.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)

    home = runtime_dir / "home"
    home.mkdir(exist_ok=True)
    env = {
        "HOME": str(home),
        "MODELS_PATH": str(runtime_dir / "models"),
        "ODIN_TEST_DOCKER_LOG": str(log_file),
        "ODIN_TEST_PREFLIGHT_BIND_HOST": preflight_bind_host,
        "ODIN_TEST_PREFLIGHT_CONFIGURED": (
            "configured" if preflight_secret_configured else ""
        ),
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "SPARK_VLLM_URL": "http://127.0.0.1:1",
    }
    result = subprocess.run(
        [str(repository / "odin.sh"), *arguments],
        cwd=repository,
        env=env,
        check=False,
        text=True,
        capture_output=True,
    )
    log = log_file.read_text(encoding="utf-8") if log_file.exists() else ""
    return result, log


def test_all_published_ports_default_to_ipv4_loopback(tmp_path: Path) -> None:
    config = _render(tmp_path)

    _assert_host_ip(config, "127.0.0.1")


def test_doctor_reads_non_loopback_host_from_selected_compose_env_file(
    tmp_path: Path,
) -> None:
    bind_host = "0.0.0.0"
    fixture_text = (
        f"ODIN_BIND_HOST={bind_host}\n"
        "NEO4J_PASSWORD=must-not-be-printed\n"
    )
    rendered = _compose_result(tmp_path / "compose", fixture_text=fixture_text)
    assert rendered.returncode == 0, rendered.stderr
    _assert_host_ip(json.loads(rendered.stdout), bind_host)

    repository = tmp_path / "repository"
    script = _copy_odin_repository(repository)
    secret_file = repository / ".env"
    secret_file.write_text(fixture_text, encoding="utf-8")
    secret_file.chmod(0o600)
    result = _doctor(tmp_path / "doctor", secret_file, script=script)

    assert result.returncode != 0
    assert "unauthenticated services" in result.stdout
    assert "ODIN_BIND_HOST=0.0.0.0" in result.stdout
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
    repository = tmp_path / "repository"
    script = _copy_odin_repository(repository)
    secret_file = repository / ".env"
    secret_value = "must-not-be-printed"
    secret_file.write_text(
        f"ODIN_BIND_HOST=127.0.0.1\nNEO4J_PASSWORD={secret_value}\n",
        encoding="utf-8",
    )
    secret_file.chmod(0o640)

    unsafe = _doctor(tmp_path / "unsafe", secret_file, script=script)
    assert unsafe.returncode != 0
    assert str(secret_file) in unsafe.stdout
    assert "expected mode 600 or stricter" in unsafe.stdout
    assert secret_value not in unsafe.stdout + unsafe.stderr

    secret_file.chmod(0o600)
    safe = _doctor(tmp_path / "safe", secret_file, script=script)
    assert safe.returncode == 0, safe.stdout + safe.stderr
    assert secret_value not in safe.stdout + safe.stderr


def test_doctor_checks_nested_repository_env_files(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    script = _copy_odin_repository(repository)
    nested = repository / "services" / "backend" / ".env"
    nested.parent.mkdir(parents=True)
    nested.write_text("NESTED_SECRET=must-not-be-printed\n", encoding="utf-8")
    nested.chmod(0o644)
    primary = repository / ".env"
    primary.write_text(
        "ODIN_BIND_HOST=127.0.0.1\nNEO4J_PASSWORD=must-not-be-printed\n",
        encoding="utf-8",
    )
    primary.chmod(0o600)

    unsafe = _doctor(
        tmp_path / "unsafe-nested",
        primary,
        script=script,
    )
    assert unsafe.returncode != 0
    assert str(nested) in unsafe.stdout
    assert "must-not-be-printed" not in unsafe.stdout + unsafe.stderr

    nested.chmod(0o600)
    safe = _doctor(
        tmp_path / "safe-nested",
        primary,
        script=script,
    )
    assert safe.returncode == 0, safe.stdout + safe.stderr


def test_doctor_reports_all_exposure_errors_and_checks_env_variants(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    script = _copy_odin_repository(repository)
    primary = repository / ".env"
    primary.write_text(
        "ODIN_BIND_HOST=0.0.0.0\nNEO4J_PASSWORD=must-not-be-printed\n",
        encoding="utf-8",
    )
    primary.chmod(0o600)
    local_env = repository / "services" / "backend" / ".env.local"
    local_env.parent.mkdir(parents=True)
    local_env.write_text("LOCAL_SECRET=must-not-be-printed\n", encoding="utf-8")
    local_env.chmod(0o644)
    spark_env = repository / ".env.spark"
    spark_env.write_text("SPARK_SECRET=must-not-be-printed\n", encoding="utf-8")
    spark_env.chmod(0o640)

    result = _doctor(tmp_path / "doctor", primary, script=script)

    assert result.returncode != 0
    assert "ODIN_BIND_HOST=0.0.0.0" in result.stdout
    assert str(local_env) in result.stdout
    assert str(spark_env) in result.stdout
    assert result.stdout.count("expected mode 600 or stricter") == 2
    assert "must-not-be-printed" not in result.stdout + result.stderr


def test_recovery_commands_work_without_environment_file_or_real_secret(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    _copy_odin_repository(repository)
    missing_env = repository / "lost.env"

    for index, command in enumerate(("ps", "down", "logs")):
        result, log = _run_odin_with_fake_compose(
            repository,
            tmp_path / f"runtime-{index}",
            ["--env-file", str(missing_env), command],
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert f" {command} " in f" {log} "
        assert "NEO4J_PASSWORD=__ODIN_RECOVERY_ONLY__" in log
        assert "ODIN_ENV_FILE=/dev/null" in log


def test_up_rejects_blank_neo4j_password_before_compose_start(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    _copy_odin_repository(repository)
    env_file = repository / ".env"
    env_file.write_text(
        "ODIN_BIND_HOST=127.0.0.1\nNEO4J_PASSWORD=\n",
        encoding="utf-8",
    )
    env_file.chmod(0o600)

    result, log = _run_odin_with_fake_compose(
        repository,
        tmp_path / "runtime",
        ["--env-file", str(env_file), "up", "interactive"],
    )

    assert result.returncode != 0
    assert "ERROR NEO4J_PASSWORD is required" in result.stdout
    assert " up " not in f" {log} "


def test_up_uses_selected_env_file_for_every_compose_call(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    _copy_odin_repository(repository)
    env_file = repository / "runtime.env"
    env_file.write_text(
        "ODIN_BIND_HOST=127.0.0.1\nNEO4J_PASSWORD=must-not-be-printed\n",
        encoding="utf-8",
    )
    env_file.chmod(0o600)

    result, log = _run_odin_with_fake_compose(
        repository,
        tmp_path / "runtime",
        ["--env-file", str(env_file), "up", "interactive"],
        preflight_secret_configured=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    calls = [call for call in log.split("---\n") if call.strip()]
    assert len(calls) >= 3
    for call in calls:
        assert f"ODIN_ENV_FILE={env_file}" in call
        assert f"--env-file {env_file}" in call
    assert any(" up -d " in f" {call} " for call in calls)
    assert "__ODIN_RECOVERY_ONLY__" not in log
    assert "must-not-be-printed" not in result.stdout + result.stderr + log


def test_examples_and_registry_contain_no_weak_neo4j_default() -> None:
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    tasks = (ROOT / "TASKS.md").read_text(encoding="utf-8")

    assert "NEO4J_PASSWORD=\n" in env_example
    assert "NEO4J_PASSWORD=odin1234" not in env_example
    assert ".env.*" in gitignore
    assert "!.env.example" in gitignore
    assert "odin_yggdrasil" not in tasks


def test_container_connections_keep_compose_dns(tmp_path: Path) -> None:
    services = _render(tmp_path)["services"]

    assert services["backend"]["environment"]["REDIS_URL"] == "redis://redis:6379/0"
    assert services["backend"]["environment"]["QDRANT_URL"] == "http://qdrant:6333"
    assert services["backend"]["environment"]["NEO4J_URL"] == "bolt://neo4j:7687"
    assert services["intelligence"]["environment"]["VLLM_URL"] == "http://vllm:8000"
