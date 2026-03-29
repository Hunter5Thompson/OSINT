"""Intelligence service configuration."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    inference_provider: str = "vllm"
    vllm_url: str = "http://localhost:8000"
    vllm_model: str = "models/qwen3.5-27b-awq"
    tei_embed_url: str = "http://localhost:8001"
    tei_rerank_url: str = "http://localhost:8002"
    embedding_dimensions: int = 1024
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "odin_intel"

    @property
    def llm_base_url(self) -> str:
        return f"{self.vllm_url}/v1"

    @property
    def llm_model(self) -> str:
        return self.vllm_model

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
