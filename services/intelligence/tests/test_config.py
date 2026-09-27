"""Phase 1 contract tests for intelligence service Settings."""

import os
from unittest.mock import patch

import pytest

from config import Settings

# Phase 1 contract: canonical collection name
_CANONICAL_COLLECTION = "odin_intel"


class TestQdrantCollectionDefault:
    """qdrant_collection default must be the canonical collection name."""

    def test_qdrant_collection_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            s = Settings(_env_file=None)
            assert s.qdrant_collection == _CANONICAL_COLLECTION


class TestExternalServiceDefaults:
    def test_gdelt_endpoint_is_configured(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            s = Settings(_env_file=None)
            assert s.gdelt_api_url == "https://api.gdeltproject.org/api/v2/doc/doc"

    def test_spatial_coverage_comes_from_index_build_artifact(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            s = Settings(_env_file=None)
            assert s.spatial_coverage_snapshot_path.name == "qdrant-coverage.json"
            assert not hasattr(s, "spatial_coverage_completeness")

    def test_free_cypher_is_disabled_by_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            assert Settings(_env_file=None).enable_free_cypher is False

    def test_free_cypher_flag_can_be_enabled_explicitly(self) -> None:
        with patch.dict(os.environ, {"ENABLE_FREE_CYPHER": "true"}, clear=True):
            assert Settings(_env_file=None).enable_free_cypher is True

    def test_neo4j_query_timeout_has_a_safe_default_and_env_override(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            assert Settings(_env_file=None).neo4j_query_timeout_s == 15.0
        with patch.dict(os.environ, {"NEO4J_QUERY_TIMEOUT_S": "2.5"}, clear=True):
            assert Settings(_env_file=None).neo4j_query_timeout_s == 2.5

    def test_neo4j_query_timeout_must_be_positive(self) -> None:
        with (
            patch.dict(os.environ, {"NEO4J_QUERY_TIMEOUT_S": "0"}, clear=True),
            pytest.raises(ValueError),
        ):
            Settings(_env_file=None)


class TestHybridFlagDefault:
    """enable_hybrid must default to False (Phase 2 gate: requires sparse vectors in Qdrant)."""

    def test_enable_hybrid_is_false_by_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            s = Settings(_env_file=None)
            # Phase 2 will flip this to True once sparse vectors exist in Qdrant.
            # Until then this must stay False to avoid silent empty-result degradation.
            assert s.enable_hybrid is False

    def test_enable_hybrid_can_be_overridden_via_env(self) -> None:
        """Ensure the flag is still configurable — just off by default."""
        with patch.dict(os.environ, {"ENABLE_HYBRID": "true"}, clear=True):
            s = Settings(_env_file=None)
            assert s.enable_hybrid is True
