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

    # Telegram Collector
    telegram_api_id: int = 0
    telegram_api_hash: str = ""
    telegram_session_path: str = "/data/telegram/odin"
    telegram_media_path: str = "/data/telegram/media"
    telegram_media_max_size: int = 20_971_520  # 20 MB
    telegram_channels_config: str = "feeds/telegram_channels.yaml"
    telegram_base_interval: int = 300   # 5 minutes
    telegram_max_interval: int = 1800   # 30 minutes

    # Vision Enrichment
    vision_vllm_url: str = "http://localhost:8011"
    vision_vllm_model: str = "qwen-vl"
    vision_queue_name: str = "vision:pending"
    vision_queue_max_pending: int = 100
    vision_dead_letter_queue: str = "vision:dead_letter"
    vision_consumer_group: str = "vision-workers"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
