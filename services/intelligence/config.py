"""Intelligence service configuration."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    inference_provider: str = "ollama"
    ollama_url: str = "http://localhost:11434"
    vllm_url: str = "http://localhost:8001"
    ollama_model: str = "qwen3:32b"
    vllm_model: str = "Qwen/Qwen3-32B"
    embedding_model: str = "nomic-embed-text"
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "worldview_intel"

    @property
    def llm_base_url(self) -> str:
        if self.inference_provider == "vllm":
            return f"{self.vllm_url}/v1"
        return self.ollama_url

    @property
    def llm_model(self) -> str:
        if self.inference_provider == "vllm":
            return self.vllm_model
        return self.ollama_model

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
