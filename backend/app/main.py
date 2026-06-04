import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db import SessionLocal, init_db
from .routers import analytics, documents, search
from .services.vector_store import index

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # rebuild the in-memory vector index from any chunks already in the DB
    db = SessionLocal()
    try:
        index.hydrate(db)
    finally:
        db.close()
    yield


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

app.include_router(documents.router)
app.include_router(search.router)
app.include_router(analytics.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
