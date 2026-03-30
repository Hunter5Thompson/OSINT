"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Google / Cesium
    cesium_ion_token: str = ""
    google_maps_api_key: str = ""

    # Flight Data
    opensky_user: str = ""
    opensky_pass: str = ""

    # Ship Data
    aisstream_api_key: str = ""

    # CCTV / Webcams
    windy_api_key: str = ""

    # LLM Inference (vLLM)
    vllm_url: str = "http://localhost:8000"
    vllm_model: str = "/models/qwen3.5-27b-awq"

    # Embeddings + Reranking (TEI)
    tei_embed_url: str = "http://localhost:8001"
    tei_rerank_url: str = "http://localhost:8002"

    # Neo4j
    neo4j_url: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str  # required: set NEO4J_PASSWORD in .env

    # Internal Services
    redis_url: str = "redis://localhost:6379/0"
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "odin_intel"
    embedding_dimensions: int = 1024
    intelligence_url: str = "http://localhost:8003"

    # External APIs
    opensky_api_url: str = "https://opensky-network.org/api/states/all"
    adsb_fi_api_url: str = "https://api.adsb.fi/v2/all"
    usgs_api_url: str = (
        "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_week.geojson"
    )
    celestrak_api_url: str = (
        "https://celestrak.org/NORAD/elements/gp.php?GROUP=active&FORMAT=tle"
    )
    aisstream_ws_url: str = "wss://stream.aisstream.io/v0/stream"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
