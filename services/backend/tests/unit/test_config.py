"""Unit tests for Settings — verifies vLLM/TEI/Neo4j fields, no Ollama."""

import pytest
from app.config import Settings


class TestSettings:
    def test_vllm_defaults(self) -> None:
        s = Settings()
        assert s.vllm_url == "http://localhost:8000"
        assert s.vllm_model == "models/qwen3.5-27b-awq"

    def test_tei_defaults(self) -> None:
        s = Settings()
        assert s.tei_embed_url == "http://localhost:8001"
        assert s.tei_rerank_url == "http://localhost:8002"

    def test_neo4j_defaults(self) -> None:
        s = Settings()
        assert s.neo4j_url == "bolt://localhost:7687"
        assert s.neo4j_user == "neo4j"
        assert s.neo4j_password == "odin1234"

    def test_no_ollama_fields(self) -> None:
        s = Settings()
        assert not hasattr(s, "ollama_url")
        assert not hasattr(s, "ollama_model")
        assert not hasattr(s, "inference_provider")
        assert not hasattr(s, "embedding_model")
