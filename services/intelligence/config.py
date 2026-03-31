"""Intelligence service configuration."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    inference_provider: str = "vllm"
    vllm_url: str = "http://localhost:8000"
    vllm_model: str = "qwen3.5"
    tei_embed_url: str = "http://localhost:8001"
    tei_rerank_url: str = "http://localhost:8002"
    embedding_dimensions: int = 1024
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "odin_intel"
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""
    # RAG feature flags
    enable_hybrid: bool = False       # Phase 2: needs sparse vectors in Qdrant
    enable_rerank: bool = True
    enable_graph_context: bool = True
    # ReAct agent guards
    react_max_tool_calls: int = 8
    react_max_iterations: int = 5
    react_tool_timeout_s: int = 15
    react_total_timeout_s: int = 120
    # Vision
    vision_max_file_size_mb: int = 10
    vision_max_dimension: int = 4096
    vision_download_timeout_s: int = 10
    vision_allowed_local_paths: list[str] = ["/tmp/odin/images/"]

    @property
    def llm_base_url(self) -> str:
        return f"{self.vllm_url}/v1"

    @property
    def llm_model(self) -> str:
        return self.vllm_model

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
