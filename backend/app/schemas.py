from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict


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


class SearchResponse(BaseModel):
    query: str
    hits: list[SearchHit]


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
