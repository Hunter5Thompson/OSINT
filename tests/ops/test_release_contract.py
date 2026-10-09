"""Render the release deployment without starting or inspecting live containers."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
IMAGE_VARIABLES = {
    "backend": "ODIN_BACKEND_IMAGE",
    "frontend": "ODIN_FRONTEND_IMAGE",
    "intelligence": "ODIN_INTELLIGENCE_IMAGE",
    "data-ingestion": "ODIN_INGESTION_IMAGE",
    "data-ingestion-spark": "ODIN_INGESTION_IMAGE",
    "vision-enrichment": "ODIN_VISION_IMAGE",
    "tei-rerank": "ODIN_RERANK_IMAGE",
}


def render_release() -> dict:
    # Use explicit files: an ambient Compose override must not change the test.
    env = {"PATH": os.environ["PATH"], "HOME": "/tmp/odin-release-test-home"}
    env.update(
        {
            variable: f"odin/{service}@sha256:{'a' * 64}"
            for service, variable in IMAGE_VARIABLES.items()
        }
    )
    env["ODIN_RELEASE_DATA_DIR"] = "/tmp/odin-release-test-data"
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
    return json.loads(result.stdout)


def validate(config: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(ROOT / "scripts/ops/validate_release.py")],
        input=json.dumps(config),
        capture_output=True,
        text=True,
        check=False,
    )


def test_release_uses_digest_images_and_has_no_local_builds():
    config = render_release()
    for name in IMAGE_VARIABLES:
        service = config["services"][name]
        assert "build" not in service
        assert service["image"].endswith("@sha256:" + "a" * 64)
    assert validate(config).returncode == 0


def test_release_preserves_model_and_persistent_inputs_and_moves_data_out_of_checkout():
    config = render_release()
    services = config["services"]
    assert services["intelligence"]["environment"]["SYNTHESIS_MODEL"] == "munin"
    command = services["vllm-9b"]["command"]
    assert command[command.index("--lora-modules") + 1] == "munin=/models/lora/munin"
    assert (
        services["data-ingestion-spark"]["environment"]["TELEGRAM_SESSION_PATH"]
        == "/data/telegram/odin"
    )
    for name, target, source in (
        ("backend", "/app/data", "/tmp/odin-release-test-data/backend"),
        ("intelligence", "/app/data/spatial", "/tmp/odin-release-test-data/backend/spatial"),
        ("data-ingestion", "/app/data/spatial", "/tmp/odin-release-test-data/backend/spatial"),
        (
            "data-ingestion-spark",
            "/app/data/spatial",
            "/tmp/odin-release-test-data/backend/spatial",
        ),
    ):
        mounts = services[name]["volumes"]
        data = next(mount for mount in mounts if mount["target"] == target)
        assert data["source"] == source
        assert data["read_only"] is True
        assert data["bind"]["create_host_path"] is False
        assert all(not mount["target"].startswith("/app/") or mount == data for mount in mounts)
    assert not services["frontend"].get("volumes")
    assert any(
        mount["target"] == "/data/gdelt" for mount in services["data-ingestion-spark"]["volumes"]
    )
    assert services["neo4j"]["volumes"][0]["type"] == "volume"
    assert services["redis"]["volumes"][0]["type"] == "volume"


@pytest.mark.parametrize(
    "image", ["odin/backend:latest", "odin/backend:a47da45", "odin/backend@sha256:abc"]
)
def test_release_guard_refuses_mutable_or_invalid_image_references(image):
    config = render_release()
    config["services"]["backend"]["image"] = image
    config["services"]["backend"]["environment"]["NEO4J_PASSWORD"] = "must-not-print-secret"
    result = validate(config)
    assert result.returncode != 0
    assert "backend" in result.stderr
    assert "must-not-print-secret" not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "name,target",
    [
        ("backend", "/app/app"),
        ("intelligence", "/app/main.py"),
        ("data-ingestion-spark", "/app"),
        ("frontend", "/usr/share/nginx/html"),
        ("backend", "/app/.venv"),
        ("frontend", "/etc/nginx/conf.d/default.conf"),
    ],
)
def test_release_guard_refuses_code_or_build_overrides(name, target):
    config = render_release()
    config["services"][name].setdefault("volumes", []).append(
        {"type": "bind", "source": "/tmp/caller-code", "target": target}
    )
    result = validate(config)
    assert result.returncode != 0
    assert name in result.stderr


def test_release_guard_refuses_reintroduced_build():
    config = render_release()
    config["services"]["intelligence"]["build"] = {"context": "/tmp/caller-code"}
    assert validate(config).returncode != 0


@pytest.mark.parametrize("field", ["command", "entrypoint"])
def test_release_guard_refuses_replaced_image_start_command(field):
    config = render_release()
    config["services"]["intelligence"][field] = ["python", "/data/caller-main.py"]
    result = validate(config)
    assert result.returncode != 0
    assert "intelligence" in result.stderr


def test_release_guard_rejects_data_from_application_checkout():
    config = render_release()
    mount = config["services"]["backend"]["volumes"][0]
    mount["source"] = str(ROOT / "services/backend/data")
    result = validate(config)
    assert result.returncode != 0
    assert "backend" in result.stderr


def run_release_start(tmp_path: Path, *, valid_images: bool, flag_first: bool = True):
    repository = tmp_path / "repo"
    repository.mkdir()
    for name in ("odin.sh", "docker-compose.yml", "docker-compose.override.yml"):
        shutil.copy2(ROOT / name, repository / name)
    for name in ("docker-compose.release.yml", "scripts/ops/validate_release.py"):
        source = ROOT / name
        if source.exists():
            target = repository / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    fixture = repository / "release.env"
    release_data = tmp_path / "release-data"
    (release_data / "backend/spatial").mkdir(parents=True)
    fixture.write_text(
        (ROOT / "tests/fixtures/compose.env").read_text()
        + f"\nODIN_RELEASE_DATA_DIR={release_data}\n"
        + "\n".join(
            f"{variable}=odin/app@sha256:{'a' * 64}"
            if valid_images
            else f"{variable}=odin/app:latest"
            for variable in set(IMAGE_VARIABLES.values())
        )
        + "\n"
    )
    (repository / "tests/fixtures").mkdir(parents=True)
    shutil.copy2(ROOT / "tests/fixtures/compose.env", repository / "tests/fixtures/compose.env")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    # Only config uses real Compose. All lifecycle operations are recorded, never run.
    docker.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, subprocess, sys\n"
        "args = sys.argv[1:]\n"
        "if 'config' in args:\n"
        "    sys.exit(subprocess.run([os.environ['REAL_DOCKER'], *args]).returncode)\n"
        "with open(os.environ['LIFECYCLE_LOG'], 'a') as f:\n"
        "    f.write(json.dumps(args) + '\\n')\n"
    )
    docker.chmod(0o755)
    curl = fake_bin / "curl"
    curl.write_text("#!/bin/sh\nexit 0\n")
    curl.chmod(0o755)
    env = {
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "HOME": str(tmp_path),
        "REAL_DOCKER": shutil.which("docker"),
        "LIFECYCLE_LOG": str(tmp_path / "lifecycle.jsonl"),
        "ODIN_WARMUP_TIMEOUT_S": "0",
    }
    options = (
        ["--release", "--env-file", str(fixture)]
        if flag_first
        else ["--env-file", str(fixture), "--release"]
    )
    result = subprocess.run(
        [str(repository / "odin.sh"), *options, "up", "interactive-spark"],
        env=env,
        cwd=repository,
        capture_output=True,
        text=True,
        check=False,
    )
    log = tmp_path / "lifecycle.jsonl"
    operations = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return result, operations


@pytest.mark.parametrize("flag_first", [True, False])
def test_release_flag_selects_explicit_files_for_every_lifecycle_operation(tmp_path, flag_first):
    result, operations = run_release_start(tmp_path, valid_images=True, flag_first=flag_first)
    assert result.returncode == 0, result.stdout + result.stderr
    assert operations
    assert any("up" in args for args in operations)
    for args in operations:
        assert "docker-compose.release.yml" in args
        assert "docker-compose.override.yml" in args


def test_invalid_release_is_rejected_before_any_stop_or_start(tmp_path):
    result, operations = run_release_start(tmp_path, valid_images=False)
    assert result.returncode != 0
    assert "digest" in result.stderr + result.stdout
    assert not operations
