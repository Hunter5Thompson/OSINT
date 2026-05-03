"""Tests for Settings — covers Spark ingestion vars, Qdrant SoT contract.

Hermeticity: default-assertion tests clear the process environment so shell-exported
`INGESTION_VLLM_*` / `VLLM_*` variables (common on dev machines) cannot flip the
assertion green/red. Codex P2 finding 2026-04-20 on commit 6449d03.
"""

import ast
import os
from pathlib import Path
from unittest.mock import patch

from config import Settings

# ---------------------------------------------------------------------------
# Phase 1 contract: canonical collection name
# ---------------------------------------------------------------------------
_CANONICAL_COLLECTION = "odin_intel"

# Repo root relative to this test file: tests/ → data-ingestion/ → services/ → repo root
_REPO_ROOT = Path(__file__).parent.parent.parent.parent


class TestQdrantCollectionDefault:
    """Runtime contract: data-ingestion Settings.qdrant_collection default."""

    def test_qdrant_collection_default(self):
        """qdrant_collection must default to the canonical collection name."""
        with patch.dict(os.environ, {}, clear=True):
            s = Settings(_env_file=None)
            assert s.qdrant_collection == _CANONICAL_COLLECTION


class TestCrossServiceQdrantCollectionConsistency:
    """AST-based cross-service guard: all four services must share the same default.

    This test does NOT import the services (hyphen-named directories break imports).
    It walks each service's config.py with the ast module and asserts the
    qdrant_collection default literal is the canonical value.
    """

    _CONFIG_PATHS = [
        "services/backend/app/config.py",
        "services/intelligence/config.py",
        "services/data-ingestion/config.py",
        "services/vision-enrichment/config.py",
    ]

    @staticmethod
    def _extract_qdrant_collection_default(config_path: Path) -> str | None:
        """Parse config.py with ast and return the qdrant_collection default literal."""
        tree = ast.parse(config_path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for stmt in node.body:
                # Match: qdrant_collection: str = "odin_intel"  (AnnAssign)
                if (
                    isinstance(stmt, ast.AnnAssign)
                    and isinstance(stmt.target, ast.Name)
                    and stmt.target.id == "qdrant_collection"
                    and isinstance(stmt.value, ast.Constant)
                    and isinstance(stmt.value.value, str)
                ):
                    return stmt.value.value
        return None

    def test_all_services_use_same_qdrant_collection_default(self):
        """All four services' config.py files must declare the same qdrant_collection default."""
        seen: dict[str, str] = {}
        for rel in self._CONFIG_PATHS:
            path = _REPO_ROOT / rel
            assert path.exists(), f"Config file not found: {path}"
            default = self._extract_qdrant_collection_default(path)
            assert default is not None, (
                f"qdrant_collection default not found in {rel}"
            )
            assert default == _CANONICAL_COLLECTION, (
                f"{rel}: qdrant_collection default is {default!r}, "
                f"expected {_CANONICAL_COLLECTION!r}"
            )
            seen[rel] = default

        # All identical — the dict values must be a single unique value
        unique = set(seen.values())
        assert len(unique) == 1, (
            f"Mismatched qdrant_collection defaults across services: {seen}"
        )


class TestDirectEnvBypassGuard:
    """Static guard: no runtime code under services/ may call os.getenv("QDRANT_COLLECTION"
    outside the allowlisted paths (config modules, tests, .env.example, docs, migration/backfill).

    Allowlist:
      - any path containing '/tests/'
      - any path with filename 'config.py'
      - '.env.example'
      - any path containing '/docs/'
      - any path containing '/migration' or '/backfill'
    """

    @staticmethod
    def _is_allowlisted(path: Path) -> bool:
        parts = path.parts
        name = path.name
        path_str = str(path)
        return (
            "/tests/" in path_str
            or "tests" in parts
            or name == "config.py"
            or name == ".env.example"
            or "/docs/" in path_str
            or "/migrations/" in path_str
            or "/backfill/" in path_str
        )

    def test_no_direct_env_reads(self):
        """No non-allowlisted .py file under services/ may call os.getenv("QDRANT_COLLECTION"."""
        needle = 'os.getenv("QDRANT_COLLECTION"'
        services_root = _REPO_ROOT / "services"
        violations: list[str] = []

        for py_file in services_root.rglob("*.py"):
            if self._is_allowlisted(py_file):
                continue
            try:
                text = py_file.read_text(errors="replace")
            except OSError:
                continue
            if needle in text:
                violations.append(str(py_file.relative_to(_REPO_ROOT)))

        assert violations == [], (
            "Direct os.getenv(\"QDRANT_COLLECTION\") calls found outside allowlist.\n"
            "Refactor these to use Settings().qdrant_collection:\n"
            + "\n".join(f"  {v}" for v in violations)
        )


class TestIngestionVllmSettings:
    def test_defaults_point_to_spark(self):
        with patch.dict(os.environ, {}, clear=True):
            s = Settings(_env_file=None)
            assert s.ingestion_vllm_url == "http://192.168.178.39:8000"
            assert s.ingestion_vllm_model == "Qwen/Qwen3.6-35B-A3B"
            assert s.ingestion_vllm_timeout == 120.0

    def test_env_override(self):
        with patch.dict(os.environ, {
            "INGESTION_VLLM_URL": "http://other:9000",
            "INGESTION_VLLM_MODEL": "test/model",
            "INGESTION_VLLM_TIMEOUT": "60.5",
        }, clear=True):
            s = Settings(_env_file=None)
            assert s.ingestion_vllm_url == "http://other:9000"
            assert s.ingestion_vllm_model == "test/model"
            assert s.ingestion_vllm_timeout == 60.5

    def test_legacy_vllm_url_preserved(self):
        """vllm_url must remain for backwards-compat with Modus D."""
        with patch.dict(os.environ, {}, clear=True):
            s = Settings(_env_file=None)
            assert s.vllm_url == "http://localhost:8000"
            assert s.vllm_model == "qwen3.5"


class TestNeo4jSettings:
    def test_bolt_driver_uri_and_http_transaction_url_are_separate(self):
        with patch.dict(
            os.environ,
            {
                "NEO4J_URL": "bolt://neo4j:7687",
                "NEO4J_HTTP_URL": "http://neo4j:7474",
            },
            clear=True,
        ):
            s = Settings(_env_file=None)
            assert s.neo4j_url == "bolt://neo4j:7687"
            assert s.neo4j_http_url == "http://neo4j:7474"
