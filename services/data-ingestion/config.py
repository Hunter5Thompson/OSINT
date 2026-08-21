"""Configuration loaded from environment variables via pydantic-settings."""

from pathlib import Path

from pydantic_settings import BaseSettings

_LOCAL_SPATIAL_CATALOG_PATH = (
    Path(__file__).resolve().parent.parent / "backend" / "data" / "spatial"
)
_DEFAULT_SPATIAL_CATALOG_PATH = (
    Path("/app/data/spatial")
    if Path("/app").is_dir()
    else _LOCAL_SPATIAL_CATALOG_PATH
)


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
    enable_hybrid: bool = False

    # HTTP settings
    http_timeout: float = 30.0
    http_max_retries: int = 3

    # Redis TTLs (seconds)
    tle_cache_ttl: int = 86400  # 24 hours
    hotspot_cache_ttl: int = 21600  # 6 hours

    # vLLM (intelligence extraction)
    vllm_url: str = "http://localhost:8000"
    vllm_model: str = "qwen3.5"

    # Ingestion LLM (Spark — Qwen3.8-27B dense, NVFP4+MTP).
    # URL WITHOUT /v1 — callers append the full path.
    ingestion_vllm_url: str = "http://192.168.178.39:8000"
    ingestion_vllm_model: str = "Qwen/Qwen3.8-27B"
    # RSS/intelligence extraction timeout (consumed by pipeline.py). Raised 120s -> 240s
    # on the 2026-08-21 cutover to Qwen3.8-27B: the dense 27B decodes at ~15-28 tok/s where
    # the Qwen3.6 MoE (3B active) did ~167, so a fully used 2000-token response needs ~70-130s
    # of generation alone and was clipping the old 120s window. Still fail-fast by intent --
    # the RSS pipeline is continuous and must not hold a worker on a wedged Spark call.
    ingestion_vllm_timeout: float = 240.0
    # NLM extraction timeout — SEPARATE from RSS (split per code review). Was 600s for the
    # 35B MoE, where a single extraction measured ~160s under concurrency. Raised to 900s for
    # Qwen3.8-27B: at ~15-28 tok/s the 8000-token NLM budget alone is ~285-533s of generation,
    # leaving 600s without headroom under concurrency. A batch job can wait; RSS should not.
    nlm_ingestion_vllm_timeout: float = 900.0
    # 8000, not 4000: long NotebookLM transcripts produce large extraction JSON; 4000
    # truncated mid-string -> JSON parse failure (the whole notebook lost). NLM extract path.
    ingestion_max_tokens: int = 8000
    event_codebook_path: Path = (
        Path(__file__).parent.parent / "intelligence" / "codebook" / "event_codebook.yaml"
    )

    # Neo4j
    # neo4j_url is the Bolt driver URI. neo4j_http_url is for the HTTP
    # transactional API used by legacy feed writers.
    neo4j_url: str = "bolt://localhost:7687"
    neo4j_http_url: str = "http://localhost:7474"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""

    # Immutable spatial assignment inputs shared with the backend catalog.
    spatial_catalog_path: Path = _DEFAULT_SPATIAL_CATALOG_PATH
    spatial_country_crosswalk_path: Path = (
        Path(__file__).resolve().parent
        / "spatial_catalog"
        / "data"
        / "country_crosswalk.json"
    )

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

    # --- Hugin P0 Collectors ---

    # UCDP (Uppsala Conflict Data Program)
    ucdp_access_token: str = ""
    ucdp_interval_hours: int = 12

    # NASA FIRMS (Fire Information)
    nasa_earthdata_key: str = ""
    firms_interval_hours: int = 2

    # USGS Earthquake
    usgs_interval_hours: int = 6

    # Military Aircraft (OpenSky fallback)
    opensky_client_id: str = ""
    opensky_client_secret: str = ""
    military_interval_minutes: int = 15

    # FIRMS-ACLED Correlation
    correlation_radius_km: float = 50.0
    correlation_time_window_days: int = 1
    correlation_min_score: float = 0.3
    correlation_interval_hours: int = 2

    # --- Hugin P1 Collectors (Sprint 2a) ---

    # EONET (NASA Earth Observatory Natural Events)
    eonet_interval_hours: int = 2

    # GDACS (Global Disaster Alerts)
    gdacs_interval_hours: int = 2

    # HAPI (Humanitarian Data Exchange)
    hapi_app_identifier: str = ""  # Base64 encoded email
    # HAPI uses CronTrigger (daily 04:00 UTC), no interval setting needed

    # NOAA NHC (Tropical Weather)
    noaa_nhc_interval_hours: int = 3

    # PortWatch (IMF Chokepoint Flows)
    portwatch_interval_hours: int = 6

    # --- Entity-type normalizer (WP-04: default ON) ---
    # ON by default: the RSS write-path canonicalizes its lowercase enum types
    # (person -> PERSON, ...) onto the canonical UPPERCASE EntityType set BEFORE
    # the MERGE (e:Entity {name, type}), so RSS and NLM writes converge on ONE
    # node per (name, type). The lowercase enum is fully covered by
    # LEGACY_ENTITY_TYPE_MAP (nlm_ingest/schemas.py); unknown values fail-soft
    # (pass through unchanged + a structlog warning). Set False only to
    # reproduce the pre-WP-04 lowercase-passthrough behaviour.
    entity_type_normalize: bool = True

    # Think-Tank Full-Text (Slice A) — opt-in (external crawls + Qdrant mutation)
    fulltext_enabled: bool = False
    crawl4ai_url: str = "http://localhost:11235"
    docling_url: str = "http://localhost:5001"
    fulltext_batch_size: int = 25
    fulltext_min_body_chars: int = 1500
    fulltext_min_paragraphs: int = 3
    fulltext_chunk_tokens: int = 650
    fulltext_chunk_overlap: int = 100
    fulltext_max_attempts: int = 4
    fulltext_rate_limit_per_domain_s: float = 2.0
    fulltext_interval_minutes: int = 60

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
