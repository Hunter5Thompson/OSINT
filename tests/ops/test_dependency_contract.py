"""Executable contract for reproducible ODIN dependency and image builds."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PYTHON_SERVICES = ("backend", "intelligence", "data-ingestion", "vision-enrichment")
DEPLOYMENT_LOCKS = (
    "services/backend/uv.lock",
    "services/intelligence/uv.lock",
    "services/data-ingestion/uv.lock",
    "services/vision-enrichment/uv.lock",
    "services/frontend/package-lock.json",
)
PYTHON_CI_JOBS = {
    "backend": "test-backend",
    "intelligence": "test-intelligence",
    "data-ingestion": "test-data-ingestion",
    "vision-enrichment": "test-vision-enrichment",
}


def _job_block(workflow: str, job: str) -> str:
    match = re.search(
        rf"^  {re.escape(job)}:\n(?P<block>.*?)(?=^  \S|\Z)",
        workflow,
        re.MULTILINE | re.DOTALL,
    )
    assert match is not None, f"missing CI job: {job}"
    return match.group("block")


def _render_frontend_build_config(
    *, spatial_scope_enabled: str | None = None
) -> dict[str, object]:
    environment = os.environ.copy()
    environment.pop("ODIN_ENV_FILE", None)
    environment.pop("VITE_SPATIAL_SCOPE_ENABLED", None)
    if spatial_scope_enabled is not None:
        environment["VITE_SPATIAL_SCOPE_ENABLED"] = spatial_scope_enabled

    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            "tests/fixtures/compose.env",
            "--profile",
            "interactive",
            "config",
            "--format",
            "json",
        ],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    config = json.loads(result.stdout)
    return config["services"]["frontend"]["build"]


@pytest.mark.parametrize("relative_path", DEPLOYMENT_LOCKS)
def test_deployment_lock_exists_and_is_tracked(relative_path: str) -> None:
    lock = ROOT / relative_path

    assert lock.is_file(), relative_path
    subprocess.run(
        ["git", "ls-files", "--error-unmatch", relative_path],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def test_lock_formats_are_current() -> None:
    for service in PYTHON_SERVICES:
        lock = (ROOT / "services" / service / "uv.lock").read_text(encoding="utf-8")
        assert lock.startswith("version = 1\n")
        assert "revision = 3\n" in lock

    package_lock = json.loads(
        (ROOT / "services" / "frontend" / "package-lock.json").read_text(
            encoding="utf-8"
        )
    )
    assert package_lock["name"] == "worldview-frontend"
    assert package_lock["lockfileVersion"] == 3


@pytest.mark.parametrize(("service", "job"), PYTHON_CI_JOBS.items())
def test_python_ci_uses_pinned_uv_and_locked_sync(service: str, job: str) -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    block = _job_block(workflow, job)

    assert f"working-directory: services/{service}" in block
    assert "uses: astral-sh/setup-uv@v5" in block
    assert 'version: "0.10.0"' in block
    assert "uv sync --locked --all-extras" in block


def test_every_ci_uv_setup_is_version_pinned() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )

    assert workflow.count("uses: astral-sh/setup-uv@v5") == workflow.count(
        'version: "0.10.0"'
    )


def test_python_lint_ci_uses_the_locked_backend_toolchain() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    block = _job_block(workflow, "lint-python")

    assert "working-directory: services/backend" in block
    assert 'version: "0.10.0"' in block
    assert "uv sync --locked --all-extras" in block
    assert "uv run --locked ruff check" in block
    assert "uvx" not in block
    assert "RUFF_VERSION" not in block


def test_frontend_ci_uses_node_22_and_npm_ci() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    block = _job_block(workflow, "test-frontend")

    assert 'node-version: "22"' in block
    assert 'VITE_SPATIAL_SCOPE_ENABLED: "true"' in block
    assert "run: npm ci" in block
    assert "run: npm install" not in block


def test_ops_contracts_have_a_hermetic_ci_job() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    block = _job_block(workflow, "test-ops-contracts")

    assert "working-directory: services/backend" in block
    assert "ODIN_ENV_FILE: tests/fixtures/compose.env" in block
    assert 'version: "0.10.0"' in block
    assert "docker compose version" in block
    assert "uv sync --locked --all-extras" in block
    assert "uv run pytest ../../tests/ops -q" in block
    assert block.index("docker compose version") < block.index("uv run pytest")


@pytest.mark.parametrize("service", PYTHON_SERVICES)
def test_python_images_install_and_run_from_lock(service: str) -> None:
    dockerfile = (ROOT / "services" / service / "Dockerfile").read_text(
        encoding="utf-8"
    )
    sync_lines = [
        line.strip() for line in dockerfile.splitlines() if line.startswith("RUN uv sync")
    ]
    command_lines = [
        line.strip() for line in dockerfile.splitlines() if line.startswith("CMD ")
    ]

    assert "ghcr.io/astral-sh/uv:0.10.0" in dockerfile
    assert "uv.lock" in dockerfile
    assert dockerfile.index("uv.lock") < dockerfile.index("RUN uv sync")
    assert sync_lines
    assert all("--locked" in line for line in sync_lines)
    assert len(command_lines) == 1
    assert '"uv", "run", "--no-sync"' in command_lines[0]


@pytest.mark.parametrize("service", ("backend", "intelligence", "vision-enrichment"))
def test_python_service_contexts_exclude_host_artifacts(service: str) -> None:
    dockerignore = ROOT / "services" / service / ".dockerignore"

    assert dockerignore.is_file()
    ignored = set(dockerignore.read_text(encoding="utf-8").splitlines())
    assert {
        ".env",
        ".env.*",
        ".venv",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
    } <= ignored
    assert "uv.lock" not in ignored


def test_frontend_image_and_context_use_frozen_install() -> None:
    service = ROOT / "services" / "frontend"
    dockerfile = (service / "Dockerfile").read_text(encoding="utf-8")
    ignored = set((service / ".dockerignore").read_text(encoding="utf-8").splitlines())

    assert "FROM node:22-alpine" in dockerfile
    assert "COPY package.json package-lock.json ./" in dockerfile
    assert "RUN npm ci" in dockerfile
    assert "RUN npm install" not in dockerfile
    assert {".env", ".env.*", "node_modules", "dist", "coverage"} <= ignored
    assert not any(pattern.startswith("!") and ".env" in pattern for pattern in ignored)
    assert "package-lock.json" not in ignored


def test_frontend_spatial_image_build_is_explicit_and_overridable() -> None:
    dockerfile = (ROOT / "services" / "frontend" / "Dockerfile").read_text(
        encoding="utf-8"
    )
    argument = "ARG VITE_SPATIAL_SCOPE_ENABLED=true"
    environment = "ENV VITE_SPATIAL_SCOPE_ENABLED=$VITE_SPATIAL_SCOPE_ENABLED"

    assert argument in dockerfile
    assert environment in dockerfile
    assert dockerfile.index(argument) < dockerfile.index("RUN npm run build")
    assert dockerfile.index(environment) < dockerfile.index("RUN npm run build")
    assert _render_frontend_build_config()["args"] == {
        "VITE_SPATIAL_SCOPE_ENABLED": "true"
    }
    assert _render_frontend_build_config(spatial_scope_enabled="false")["args"] == {
        "VITE_SPATIAL_SCOPE_ENABLED": "false"
    }


def test_frontend_automated_builds_share_the_spatial_default() -> None:
    quality_loop = (ROOT / "ops" / "quality-loop" / "quality_loop.sh").read_text(
        encoding="utf-8"
    )
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert 'FRONTEND_SPATIAL_SCOPE_ENABLED="${VITE_SPATIAL_SCOPE_ENABLED:-true}"' in (
        quality_loop
    )
    assert (
        'env "VITE_SPATIAL_SCOPE_ENABLED=$FRONTEND_SPATIAL_SCOPE_ENABLED" npm run build'
        in quality_loop
    )
    assert "VITE_SPATIAL_SCOPE_ENABLED=true" in env_example.splitlines()


def test_frontend_cesium_version_matches_the_qualified_install() -> None:
    service = ROOT / "services" / "frontend"
    manifest = json.loads((service / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((service / "package-lock.json").read_text(encoding="utf-8"))

    assert manifest["dependencies"]["cesium"] == "1.142.0"
    assert manifest["overrides"]["@cesium/engine"] == "26.0.0"
    assert manifest["overrides"]["@cesium/widgets"] == "16.0.0"
    assert lock["packages"][""]["dependencies"]["cesium"] == "1.142.0"
    assert lock["packages"]["node_modules/cesium"]["version"] == "1.142.0"
    engine_versions = {
        package["version"]
        for path, package in lock["packages"].items()
        if path.endswith("node_modules/@cesium/engine")
    }
    widget_versions = {
        package["version"]
        for path, package in lock["packages"].items()
        if path.endswith("node_modules/@cesium/widgets")
    }
    assert engine_versions == {"26.0.0"}
    assert widget_versions == {"16.0.0"}


def test_quality_loop_uses_frozen_installs() -> None:
    quality_loop = (ROOT / "ops" / "quality-loop" / "quality_loop.sh").read_text(
        encoding="utf-8"
    )

    assert quality_loop.count("uv sync --locked --all-extras") == 4
    assert "uv sync --all-extras" not in quality_loop
    assert "uv run --with" not in quality_loop
    assert "npm ci" in quality_loop
    assert "npm install" not in quality_loop


def test_nested_ops_uv_runner_cannot_update_the_ingestion_lock() -> None:
    source = (ROOT / "tests" / "ops" / "test_quality_loop.py").read_text(
        encoding="utf-8"
    )
    match = re.search(
        r"def test_default_ingestion_suite_excludes_live_spark_smoke.*?(?=\n    def |\Z)",
        source,
        re.DOTALL,
    )

    assert match is not None
    commands = re.findall(r'\[\s*"uv",\s*"run",.*?\]', match.group(0), re.DOTALL)
    assert commands
    assert all('"--locked"' in command for command in commands)
    assert all(
        command.index('"--locked"') < command.index('"pytest"')
        for command in commands
    )


@pytest.mark.parametrize("service", PYTHON_SERVICES)
def test_coverage_runner_is_part_of_each_service_lock(service: str) -> None:
    lock = (ROOT / "services" / service / "uv.lock").read_text(encoding="utf-8")

    assert re.search(r'^name = "pytest-cov"$', lock, re.MULTILINE)


def test_agents_documents_tracked_lock_policy_and_frozen_commands() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

    for relative_path in DEPLOYMENT_LOCKS:
        assert relative_path in agents
    assert "uv 0.10.0" in agents
    assert "uv sync --locked --all-extras" in agents
    assert "npm ci" in agents
    assert "Node 22" in agents


def test_uv_lock_check_characterization_rejects_manifest_drift(
    tmp_path: Path,
) -> None:
    """Characterize uv; deployment-path wiring is asserted separately above."""
    source = ROOT / "services" / "data-ingestion"
    project = tmp_path / "project"
    project.mkdir()
    shutil.copy2(source / "pyproject.toml", project / "pyproject.toml")
    shutil.copy2(source / "uv.lock", project / "uv.lock")
    manifest = project / "pyproject.toml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            '"httpx>=0.27",',
            '"httpx>=0.27",\n    "sniffio==1.3.1",',
            1,
        ),
        encoding="utf-8",
    )
    before = (project / "uv.lock").read_bytes()

    result = subprocess.run(
        ["uv", "lock", "--check"],
        cwd=project,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert (project / "uv.lock").read_bytes() == before
