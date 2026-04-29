"""Tests for Settings — covers Spark ingestion vars.

Hermeticity: default-assertion tests clear the process environment so shell-exported
`INGESTION_VLLM_*` / `VLLM_*` variables (common on dev machines) cannot flip the
assertion green/red. Codex P2 finding 2026-04-20 on commit 6449d03.
"""

import os
from unittest.mock import patch

from config import Settings


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
