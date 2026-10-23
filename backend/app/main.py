import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db import init_db
from .monitoring import PrometheusMiddleware, metrics_response
from .routers import analytics, documents, search, jobs
from .telemetry import configure_telemetry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    provider = configure_telemetry("idp-api")
    try:
        yield
    finally:
        provider.shutdown()


app = FastAPI(
    title="Intelligent Document Processing Platform",
    description="Upload documents → extract, classify, summarize, and search with LLMs.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)
app.add_middleware(PrometheusMiddleware)

app.include_router(documents.router)
app.include_router(search.router)
app.include_router(analytics.router)
app.include_router(jobs.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/metrics", include_in_schema=False)
def metrics():
    return metrics_response()
