import re
import subprocess
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SERVICE_ROOT = REPO_ROOT / "services" / "data-ingestion"


def test_root_dockerignore_excludes_local_and_secret_paths():
    dockerignore = (REPO_ROOT / ".dockerignore").read_text().splitlines()

    assert {
        ".git",
        ".claude/worktrees",
        "**/.env",
        "**/.env.*",
        "**/.venv",
        "**/__pycache__",
        "**/.pytest_cache",
        "**/.ruff_cache",
        "**/node_modules",
        "**/dist",
    } <= set(dockerignore)


def test_data_ingestion_uv_lock_is_tracked_and_reincluded():
    assert (SERVICE_ROOT / "uv.lock").is_file()
    subprocess.run(
        ["git", "ls-files", "--error-unmatch", "uv.lock"],
        cwd=SERVICE_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    gitignore = (REPO_ROOT / ".gitignore").read_text()
    assert "!services/data-ingestion/uv.lock" in gitignore


def test_data_ingestion_dockerfile_packages_runtime_contract():
    dockerfile = (SERVICE_ROOT / "Dockerfile").read_text()

    assert "COPY --from=ghcr.io/astral-sh/uv:0.10.0 /uv /usr/local/bin/uv" in dockerfile
    assert "COPY services/data-ingestion/pyproject.toml ." in dockerfile
    assert "COPY services/data-ingestion/uv.lock ." in dockerfile
    assert "COPY services/data-ingestion/canonicalize.py ." in dockerfile
    assert "COPY services/data-ingestion/graph_integrity/ graph_integrity/" in dockerfile
    assert "COPY services/data-ingestion/qdrant_doctor/ qdrant_doctor/" in dockerfile
    assert "COPY services/data-ingestion/infra_atlas/ infra_atlas/" in dockerfile
    assert "COPY services/data-ingestion/spatial_catalog/ spatial_catalog/" not in dockerfile
    assert (
        "COPY services/intelligence/codebook/event_codebook.yaml "
        "runtime_contracts/event_codebook.yaml"
    ) in dockerfile
    assert 'ENV EVENT_CODEBOOK_PATH="/app/runtime_contracts/event_codebook.yaml"' in dockerfile
    assert "RUN uv sync --locked --no-dev --no-install-project" in dockerfile
    assert "RUN uv sync --locked --no-dev" in dockerfile
    # Runtime entrypoint must use the built venv python directly — never `uv run`,
    # which re-resolves and would pull dev deps (ruff/duckdb/...) at container start
    # and can fail offline.
    assert 'CMD ["python", "scheduler.py"]' in dockerfile
    assert "uv run" not in dockerfile
    assert "COPY . ." not in dockerfile
    assert "migrations/" not in dockerfile


def test_spatial_compiler_dependencies_and_sources_are_build_time_only():
    pyproject_path = SERVICE_ROOT / "pyproject.toml"
    pyproject = pyproject_path.read_text()
    configuration = tomllib.loads(pyproject)
    project = configuration["project"]
    wheel = configuration["tool"]["hatch"]["build"]["targets"]["wheel"]

    assert not any(dependency.startswith("shapely") for dependency in project["dependencies"])
    assert project["optional-dependencies"]["spatial-catalog"] == ["shapely>=2.1,<2.2"]
    assert not any(path.startswith("spatial_catalog/") for path in wheel["include"])
    assert "spatial_catalog/**" in wheel["exclude"]
    assert "tests/test_spatial_catalog_*.py" in wheel["exclude"]
    assert "services/data-ingestion/spatial_catalog" in (
        REPO_ROOT / ".dockerignore"
    ).read_text().splitlines()


def test_compose_builds_data_ingestion_images_from_repo_root():
    compose = (REPO_ROOT / "docker-compose.yml").read_text()

    for service in ("data-ingestion", "data-ingestion-spark"):
        match = re.search(
            rf"^  {re.escape(service)}:\n(?P<block>.*?)(?=^  \S|\Z)",
            compose,
            re.M | re.S,
        )
        assert match is not None
        block = match.group("block")
        assert "context: ." in block
        assert "dockerfile: services/data-ingestion/Dockerfile" in block


def test_agents_documents_deployment_lock_exception():
    agents = (REPO_ROOT / "AGENTS.md").read_text()

    assert "except" in agents
    assert "services/data-ingestion/uv.lock" in agents
