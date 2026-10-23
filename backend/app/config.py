from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, model_validator

BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    openai_api_key: str = ""
    openai_chat_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    answer_model: str = ""  # empty uses openai_chat_model
    complex_model: str = ""  # optional route for quality=high
    redis_url: str = "redis://localhost:6379/0"
    worker_concurrency: int = Field(4, ge=1, le=32)
    worker_metrics_port: int = 8001
    job_max_attempts: int = Field(3, ge=1)
    job_lease_seconds: int = Field(180, ge=30)
    retry_base_seconds: int = Field(5, ge=1)
    llm_concurrency: int = Field(4, ge=1)
    llm_timeout_seconds: float = Field(60, gt=0, le=120)
    llm_input_tokens: int = Field(12000, ge=1000)
    llm_output_tokens: int = Field(1000, ge=100)
    embedding_batch_size: int = Field(64, ge=1, le=128)
    embedding_batch_tokens: int = Field(60000, ge=8192, le=100000)
    cache_ttl_seconds: int = Field(3600, ge=0)
    chunk_tokens: int = Field(400, ge=32, le=2000)
    chunk_overlap_tokens: int = Field(60, ge=0)
    retrieval_candidates: int = Field(30, ge=5, le=100)
    reranker: str = "llm"  # llm or lexical
    rag_context_tokens: int = Field(6000, ge=256)
    otel_exporter_otlp_endpoint: str = ""
    # USD per million tokens: configure for each deployed model; unknown costs stay null.
    model_prices: dict[str, dict[str, float]] = {}

    @model_validator(mode="after")
    def validate_budgets(self):
        if self.chunk_overlap_tokens >= self.chunk_tokens:
            raise ValueError("chunk_overlap_tokens must be smaller than chunk_tokens")
        if self.rag_context_tokens + 2000 > self.llm_input_tokens:
            raise ValueError("Reserve 2000 input tokens above rag_context_tokens")
        if self.reranker not in {"llm", "lexical"}:
            raise ValueError("reranker must be llm or lexical")
        return self

    database_url: str = "sqlite:///./data/idp.db"
    upload_dir: str = "./uploads"
    max_upload_mb: int = 25
    max_document_tokens: int = Field(200000, ge=1000)

    @property
    def upload_path(self) -> Path:
        p = Path(self.upload_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()
