"""Configuration for the Vision Enrichment service."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Vision service settings — all values from env vars or .env."""

    redis_url: str = "redis://localhost:6379/0"
    vision_vllm_url: str = "http://localhost:8011/v1"
    vision_vllm_model: str = "qwen-vl"

    # Queue settings
    vision_queue_name: str = "vision:pending"
    vision_consumer_group: str = "vision-workers"
    vision_consumer_name: str = "worker-1"
    vision_dead_letter_queue: str = "vision:dead_letter"
    vision_max_retries: int = 3
    vision_idle_timeout_ms: int = 600_000  # 10 min for XAUTOCLAIM

    # Neo4j (for updating Document nodes)
    neo4j_url: str = "http://localhost:7474"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""

    # Qdrant (for updating payloads)
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "odin_intel"

    # Redis Streams (enriched events)
    redis_stream_enriched: str = "events:enriched"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
