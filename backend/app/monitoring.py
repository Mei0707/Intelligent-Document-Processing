"""Prometheus metrics for API, document pipeline, and semantic search."""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Iterator

from fastapi import Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware
from .telemetry import span


HTTP_REQUESTS_TOTAL = Counter(
    "idp_http_requests_total",
    "HTTP requests processed by the API.",
    ("method", "path", "status"),
)
HTTP_REQUEST_SECONDS = Histogram(
    "idp_http_request_seconds",
    "HTTP request latency in seconds.",
    ("method", "path"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)

DOCUMENT_UPLOADS_TOTAL = Counter(
    "idp_document_uploads_total",
    "Documents uploaded to the platform.",
    ("mime_type",),
)
DOCUMENT_UPLOAD_BYTES = Histogram(
    "idp_document_upload_bytes",
    "Uploaded document size in bytes.",
    buckets=(1_000, 10_000, 100_000, 1_000_000, 5_000_000, 10_000_000, 25_000_000),
)
DOCUMENTS_PROCESSING = Gauge(
    "idp_documents_processing",
    "Documents currently running through the processing pipeline.",
)
DOCUMENT_PROCESSING_TOTAL = Counter(
    "idp_document_processing_total",
    "Document processing completions by outcome.",
    ("outcome", "category", "error_type"),
)
DOCUMENT_PROCESSING_STAGE_SECONDS = Histogram(
    "idp_document_processing_stage_seconds",
    "Document processing stage duration in seconds.",
    ("stage",),
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120),
)
DOCUMENT_PROCESSING_TOTAL_SECONDS = Histogram(
    "idp_document_processing_total_seconds",
    "End-to-end document processing duration in seconds.",
    buckets=(0.1, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600),
)
DOCUMENT_CHUNKS_TOTAL = Counter(
    "idp_document_chunks_total",
    "Text chunks generated for processed documents.",
    ("category",),
)
VECTOR_INDEX_ENTRIES = Gauge(
    "idp_vector_index_entries",
    "Chunk vectors currently loaded in the in-memory vector index.",
)

SEARCH_QUERIES_TOTAL = Counter(
    "idp_search_queries_total",
    "Semantic search queries processed.",
    ("outcome",),
)
SEARCH_QUERY_SECONDS = Histogram(
    "idp_search_query_seconds",
    "Semantic search latency in seconds.",
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
SEARCH_HITS = Histogram(
    "idp_search_hits",
    "Number of semantic search hits returned.",
    buckets=(0, 1, 2, 3, 5, 10, 20, 50),
)



def metrics_response() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


def _normalize_path(request: Request) -> str:
    route = request.scope.get("route")
    if route is not None and getattr(route, "path", None):
        return str(route.path)
    return "unmatched"


class PrometheusMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/metrics":
            return await call_next(request)

        start = time.perf_counter()
        status = "500"
        try:
            with span("http.request", carrier=dict(request.headers), method=request.method):
                response = await call_next(request)
            status = str(response.status_code)
            return response
        finally:
            elapsed = time.perf_counter() - start
            path = _normalize_path(request)
            HTTP_REQUESTS_TOTAL.labels(request.method, path, status).inc()
            HTTP_REQUEST_SECONDS.labels(request.method, path).observe(elapsed)


@contextmanager
def pipeline_stage(stage: str) -> Iterator[None]:
    start = time.perf_counter()
    try:
        with span("pipeline." + stage):
            yield
    finally:
        DOCUMENT_PROCESSING_STAGE_SECONDS.labels(stage).observe(time.perf_counter() - start)


@contextmanager
def search_timer() -> Iterator[None]:
    start = time.perf_counter()
    try:
        yield
    finally:
        SEARCH_QUERY_SECONDS.observe(time.perf_counter() - start)


def record_document_upload(mime_type: str, size_bytes: int) -> None:
    DOCUMENT_UPLOADS_TOTAL.labels(mime_type or "application/octet-stream").inc()
    DOCUMENT_UPLOAD_BYTES.observe(size_bytes)


def record_document_processing(outcome: str, category: str | None, error_type: str = "") -> None:
    DOCUMENT_PROCESSING_TOTAL.labels(outcome, category or "unknown", error_type or "none").inc()


def record_document_chunks(category: str | None, count: int) -> None:
    if count > 0:
        DOCUMENT_CHUNKS_TOTAL.labels(category or "unknown").inc(count)


def record_search(outcome: str, hit_count: int | None = None) -> None:
    SEARCH_QUERIES_TOTAL.labels(outcome).inc()
    if hit_count is not None:
        SEARCH_HITS.observe(hit_count)

LLM_CALLS = Counter("idp_llm_calls_total", "Provider requests by outcome", ("model", "operation", "outcome"))
LLM_SECONDS = Histogram("idp_llm_seconds", "Provider latency including permit acquisition", ("model", "operation"),
                        buckets=(.05, .1, .25, .5, 1, 2, 5, 10, 30, 60, 120))
LLM_TOKENS = Counter("idp_llm_tokens_total", "Billed input, output and cached-input tokens", ("model", "kind"))
LLM_COST = Counter("idp_llm_estimated_cost_usd_total", "Estimated cost for models with configured prices", ("model",))
CACHE_HITS = Counter("idp_inference_cache_hits_total", "Application response cache hits", ("operation",))
RETRIEVAL_SECONDS = Histogram("idp_retrieval_seconds", "Retrieval and reranking latency", ("strategy",),
                              buckets=(.001, .01, .05, .1, .5, 1, 5, 10, 30, 60))
JOB_SECONDS = Histogram("idp_job_seconds", "Job attempt latency", buckets=(.1, 1, 5, 10, 30, 60, 120, 300, 600))
JOB_OUTCOMES = Counter("idp_job_attempts_total", "Worker attempt outcomes", ("outcome",))
QUEUE_DEPTH = Gauge("idp_queue_depth", "Durable job counts by state", ("state",))
QUEUE_WAIT = Histogram("idp_queue_wait_seconds", "Time from job creation to start", buckets=(.1, 1, 5, 10, 30, 60, 300, 600))
