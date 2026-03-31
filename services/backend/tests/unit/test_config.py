"""Unit tests for Settings — verifies vLLM/TEI/Neo4j fields, no Ollama."""

from app.config import Settings


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
        assert s.flight_cache_ttl_s == 30

    def test_cable_config_defaults(self) -> None:
        s = Settings(
            _env_file=None,
            neo4j_password="test-secret",
        )
        assert "submarinecablemap.com" in s.cable_geo_url
        assert "submarinecablemap.com" in s.landing_point_geo_url
        assert s.cable_cache_ttl_s == 86400
