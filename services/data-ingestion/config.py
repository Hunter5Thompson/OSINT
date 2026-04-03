"""Configuration loaded from environment variables via pydantic-settings."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings — all values come from env vars or .env file."""

    # Internal service URLs
    redis_url: str = "redis://localhost:6379/0"
    qdrant_url: str = "http://localhost:6333"
    tei_embed_url: str = "http://localhost:8001"

    # Embedding configuration
    embedding_dimensions: int = 1024

    # Qdrant collection
    qdrant_collection: str = "odin_intel"

    # HTTP settings
    http_timeout: float = 30.0
    http_max_retries: int = 3

    # Redis TTLs (seconds)
    tle_cache_ttl: int = 86400  # 24 hours
    hotspot_cache_ttl: int = 21600  # 6 hours

    # vLLM (intelligence extraction)
    vllm_url: str = "http://localhost:8000"
    vllm_model: str = "qwen3.5"

    # Neo4j (graph writes via HTTP transactional API)
    neo4j_url: str = "http://localhost:7474"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""

    # Redis Streams
    redis_stream_events: str = "events:new"

    # NotebookLM / Voxtral
    voxtral_url: str = "http://localhost:8010/v1"
    voxtral_model: str = "voxtral"
    nlm_data_dir: str = "/home/deadpool-ultra/ODIN/odin-data/notebooklm"
    claude_model: str = "claude-sonnet-4-20250514"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
