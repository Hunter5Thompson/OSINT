import os
import re
import subprocess
import sys
import sysconfig
import tomllib
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SERVICE_ROOT = REPO_ROOT / "services" / "data-ingestion"
SPATIAL_RUNTIME_FILES = frozenset(
    {
        "spatial_catalog/__init__.py",
        "spatial_catalog/identity.py",
        "spatial_catalog/manifest.py",
        "spatial_catalog/models.py",
        "spatial_catalog/normalize.py",
        "spatial_catalog/source_lock.py",
        "spatial_catalog/topology.py",
        "spatial_catalog/catalog-plan.json",
        "spatial_catalog/data/country_crosswalk.json",
    }
)
SPATIAL_COMPILER_FILES = frozenset(
    {
        "spatial_catalog/__main__.py",
        "spatial_catalog/audit.py",
        "spatial_catalog/compiler.py",
        "spatial_catalog/emit.py",
        "spatial_catalog/lod.py",
        "spatial_catalog/tools/rebuild_mapshaper_bundle.py",
    }
)
SPATIAL_DOCKER_CONTEXT_EXCLUDES = frozenset(
    {
        "services/data-ingestion/spatial_catalog/__main__.py",
        "services/data-ingestion/spatial_catalog/audit.py",
        "services/data-ingestion/spatial_catalog/compiler.py",
        "services/data-ingestion/spatial_catalog/emit.py",
        "services/data-ingestion/spatial_catalog/lod.py",
        "services/data-ingestion/spatial_catalog/tools",
        "services/data-ingestion/spatial_catalog/data/*",
    }
)


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
    assert (
        "COPY services/data-ingestion/migrations/location_spatial_scope_indexes.cypher "
        "migrations/location_spatial_scope_indexes.cypher"
    ) in dockerfile
    assert "COPY services/data-ingestion/qdrant_doctor/ qdrant_doctor/" in dockerfile
    assert "COPY services/data-ingestion/infra_atlas/ infra_atlas/" in dockerfile
    assert "COPY services/backend/data/spatial/ data/spatial/" in dockerfile
    assert "COPY services/data-ingestion/spatial_catalog/ spatial_catalog/" not in dockerfile
    for relative_path in sorted(SPATIAL_RUNTIME_FILES):
        assert (
            f"COPY services/data-ingestion/{relative_path} {relative_path}"
            in dockerfile
        )
    for relative_path in sorted(SPATIAL_COMPILER_FILES):
        assert f"COPY services/data-ingestion/{relative_path}" not in dockerfile
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
    assert "COPY services/data-ingestion/migrations/ migrations/" not in dockerfile


def test_spatial_normalizer_dependencies_are_available_at_runtime():
    pyproject_path = SERVICE_ROOT / "pyproject.toml"
    pyproject = pyproject_path.read_text()
    configuration = tomllib.loads(pyproject)
    project = configuration["project"]
    dockerignore = set((REPO_ROOT / ".dockerignore").read_text().splitlines())

    assert "shapely>=2.1,<2.2" in project["dependencies"]
    assert project["optional-dependencies"]["spatial-catalog"] == ["shapely>=2.1,<2.2"]
    assert "services/data-ingestion/spatial_catalog" not in dockerignore
    assert dockerignore >= SPATIAL_DOCKER_CONTEXT_EXCLUDES
    assert "!services/data-ingestion/spatial_catalog/data/country_crosswalk.json" in (
        dockerignore
    )
    for relative_path in SPATIAL_RUNTIME_FILES - {
        "spatial_catalog/data/country_crosswalk.json"
    }:
        assert f"services/data-ingestion/{relative_path}" not in dockerignore


def test_built_wheel_imports_infra_atlas_with_identity_but_without_compiler(
    tmp_path: Path,
) -> None:
    distribution = tmp_path / "dist"
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(distribution)],
        cwd=SERVICE_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    wheels = tuple(distribution.glob("*.whl"))
    assert len(wheels) == 1
    installed = tmp_path / "installed"
    with zipfile.ZipFile(wheels[0]) as wheel:
        members = set(wheel.namelist())
        wheel.extractall(installed)

    packaged_spatial = {
        name for name in members if name.startswith("spatial_catalog/")
    }
    assert packaged_spatial == SPATIAL_RUNTIME_FILES
    assert "graph_integrity/spatial_normalizer.py" in members
    assert "gdelt_raw/migrations/phase2_indexes.cypher" in members
    assert "migrations/location_spatial_scope_indexes.cypher" in members
    assert not SPATIAL_COMPILER_FILES & members
    assert not any(
        name.startswith("spatial_catalog/tools/") or name.endswith(".tgz")
        for name in members
    )

    environment = os.environ.copy()
    environment.pop("PYTHONHOME", None)
    environment.pop("PYTHONPATH", None)
    purelib = sysconfig.get_path("purelib")
    isolated_import = "\n".join(
        (
            "import importlib.util",
            "import pathlib",
            "import sys",
            f"sys.path.insert(0, {str(installed)!r})",
            f"sys.path.append({purelib!r})",
            "import infra_atlas.build_country_almanac as almanac",
            "import infra_atlas.cli as infra_cli",
            "import spatial_catalog.identity as identity",
            f"root = pathlib.Path({str(installed)!r}).resolve()",
            "assert pathlib.Path(infra_cli.__file__).resolve().is_relative_to(root)",
            "assert pathlib.Path(identity.__file__).resolve().is_relative_to(root)",
            "assert callable(infra_cli.cli)",
            "assert almanac.FRONTEND_TOPO == root / 'services/frontend/public/countries-110m.json'",
            "assert almanac.SEED_OUT == root / 'services/backend/data/country_almanac.json'",
            "assert identity.load_country_crosswalk().records",
            "assert importlib.util.find_spec('spatial_catalog.compiler') is None",
            "assert 'shapely' not in sys.modules",
        )
    )
    subprocess.run(
        [sys.executable, "-S", "-c", isolated_import],
        cwd=installed,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


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
