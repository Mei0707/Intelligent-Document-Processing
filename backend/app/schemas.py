from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class DocumentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    uploaded_at: datetime
    status: str
    category: str | None = None
    category_confidence: float | None = None
    summary: str | None = None
    size_bytes: int
    error: str | None = None


class DocumentDetail(DocumentSummary):
    job_id: str | None = None
    extracted_fields: dict[str, Any] | None = None
    raw_text: str | None = None
    token_count: int | None = None
    mime_type: str


class DocumentList(BaseModel):
    items: list[DocumentSummary]
    total: int


class SearchHit(BaseModel):
    document_id: int
    filename: str
    category: str | None
    snippet: str
    score: float
    chunk_id: int
    chunk_index: int


class SearchResponse(BaseModel):
    query: str
    hits: list[SearchHit]
    strategy: str


class AnswerRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    strategy: Literal["bm25", "vector", "hybrid", "hybrid_rerank"] = "hybrid"
    top_k: int = Field(5, ge=1, le=20)
    quality: Literal["balanced", "high"] = "balanced"


class Citation(BaseModel):
    label: int
    document_id: int
    chunk_id: int
    chunk_index: int
    filename: str
    quote: str
    url: str


class AnswerResponse(BaseModel):
    question: str
    answer: str
    citations: list[Citation]
    abstained: bool
    strategy: str
    latency_ms: float
    usage: dict[str, Any]


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    document_id: int
    status: str
    stage: str
    attempts: int
    error: str | None
    created_at: datetime
    updated_at: datetime
    available_at: datetime


class CategoryStat(BaseModel):
    category: str
    count: int


class AnalyticsResponse(BaseModel):
    total_documents: int
    processed: int
    failed: int
    pending: int
    by_category: list[CategoryStat]
    recent: list[DocumentSummary]
