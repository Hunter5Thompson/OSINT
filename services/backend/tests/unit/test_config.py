"""Unit tests for Settings — verifies vLLM/TEI/Neo4j fields, no Ollama."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.models.timeline import ChronikExactSpatialActivationV1

# Phase 1 contract: canonical collection name
_CANONICAL_COLLECTION = "odin_intel"


class TestQdrantCollectionDefault:
    """Phase 1 contract: qdrant_collection default must be odin_intel."""

    def test_qdrant_collection_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            s = Settings(_env_file=None, neo4j_password="test-secret")
            assert s.qdrant_collection == _CANONICAL_COLLECTION


class TestSettings:
    def test_vllm_defaults(self) -> None:
        s = Settings(
            _env_file=None,
            neo4j_password="test-secret",
        )
        assert s.vllm_url == "http://localhost:8000"
        assert s.vllm_model == "qwen3.5"

    def test_tei_defaults(self) -> None:
        s = Settings(
            _env_file=None,
            neo4j_password="test-secret",
        )
        assert s.tei_embed_url == "http://localhost:8001"
        assert s.tei_rerank_url == "http://localhost:8002"

    def test_neo4j_fields_present(self) -> None:
        s = Settings(
            _env_file=None,
            neo4j_url="bolt://localhost:7687",
            neo4j_user="neo4j",
            neo4j_password="test-secret",
        )
        assert s.neo4j_url == "bolt://localhost:7687"
        assert s.neo4j_user == "neo4j"
        assert s.neo4j_password == "test-secret"

    def test_no_ollama_fields(self) -> None:
        s = Settings(
            _env_file=None,
            neo4j_password="test-secret",
        )
        assert not hasattr(s, "ollama_url")
        assert not hasattr(s, "ollama_model")
        assert not hasattr(s, "inference_provider")
        assert not hasattr(s, "embedding_model")

    def test_flight_cache_ttl_default(self) -> None:
        s = Settings(
            _env_file=None,
            neo4j_password="test-secret",
        )
        assert s.flight_cache_ttl_s == 300

    def test_cable_config_defaults(self) -> None:
        s = Settings(
            _env_file=None,
            neo4j_password="test-secret",
        )
        assert "submarinecablemap.com" in s.cable_geo_url
        assert "submarinecablemap.com" in s.landing_point_geo_url
        assert s.cable_cache_ttl_s == 86400

    def test_spatial_catalog_defaults(self) -> None:
        settings = Settings(_env_file=None, neo4j_password="test-secret")

        assert settings.spatial_catalog_path == Path("/app/data/spatial")
        assert settings.spatial_asset_max_concurrency == 8
        assert settings.spatial_asset_acquire_timeout_s == 0.05
        assert settings.chronik_exact_spatial_activations == ()

    def test_exact_spatial_activation_is_strict_server_side_deployment_data(self) -> None:
        activation = {
            "schema_version": 1,
            "lane": "event_occurrence",
            "scope_kind": "country",
            "catalog_revision": "spatial-v1-0123456789ab",
            "derivation_revision": "spatial-derive-v1-0123456789ab",
            "coverage_revision": "coverage-fixture-a",
            "enabled": True,
            "coverage_complete": True,
            "index_plan_verified": True,
            "stale_revision_ratio": 0.0,
        }

        settings = Settings(
            _env_file=None,
            neo4j_password="test-secret",
            chronik_exact_spatial_activations=[activation],
        )

        assert settings.chronik_exact_spatial_activations == (
            ChronikExactSpatialActivationV1.model_validate(activation),
        )

        with pytest.raises(ValidationError):
            Settings(
                _env_file=None,
                neo4j_password="test-secret",
                chronik_exact_spatial_activations=[
                    activation,
                    {**activation, "unexpected": "client-controlled"},
                ],
            )

    def test_exact_spatial_activation_rejects_duplicate_lane_kind_entries(self) -> None:
        activation = {
            "lane": "event_occurrence",
            "scope_kind": "country",
            "catalog_revision": "spatial-v1-0123456789ab",
            "derivation_revision": "spatial-derive-v1-0123456789ab",
            "coverage_revision": "coverage-fixture-a",
            "enabled": True,
            "coverage_complete": True,
            "index_plan_verified": True,
            "stale_revision_ratio": 0.0,
        }

        with pytest.raises(ValidationError, match="lane/kind"):
            Settings(
                _env_file=None,
                neo4j_password="test-secret",
                chronik_exact_spatial_activations=[activation, activation],
            )

    @pytest.mark.parametrize(
        ("name", "value"),
        [
            ("spatial_asset_max_concurrency", 0),
            ("spatial_asset_max_concurrency", 65),
            ("spatial_asset_acquire_timeout_s", 0),
            ("spatial_asset_acquire_timeout_s", 5.1),
        ],
    )
    def test_spatial_resource_limits_are_bounded(self, name: str, value: float) -> None:
        with pytest.raises(ValidationError):
            Settings(
                _env_file=None,
                neo4j_password="test-secret",
                **{name: value},
            )
