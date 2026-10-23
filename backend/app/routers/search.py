import time
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from redis.exceptions import RedisError
from openai import OpenAIError
from .. import schemas
from ..db import get_db
from ..monitoring import record_search, search_timer
from ..services.llm import measure_usage
from ..services.retrieval import Corpus, retrieve
from ..services.rag import answer

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("", response_model=schemas.SearchResponse)
def search(q: str = Query(..., min_length=1, max_length=2000),
           top_k: int = Query(10, ge=1, le=50),
           strategy: Literal["bm25", "vector", "hybrid", "hybrid_rerank"] = "hybrid",
           db: Session = Depends(get_db)):
    if not q.strip():
        raise HTTPException(422, "Query must contain text")
    with search_timer():
        try:
            hits = retrieve(q, Corpus.from_db(db), strategy, top_k)
        except (RuntimeError, ValueError, RedisError, OpenAIError):
            record_search("failed")
            raise HTTPException(503, "Retrieval unavailable; check inference configuration and worker logs")
        record_search("success", len(hits))
    return {"query": q, "strategy": strategy, "hits": [
        {"document_id": c.document_id, "filename": c.filename, "category": c.category,
         "chunk_id": c.chunk_id, "chunk_index": c.chunk_index, "score": c.score,
         "snippet": " ".join(c.text.split())[:500]} for c in hits]}


@router.post("/answer", response_model=schemas.AnswerResponse)
def answer_question(request: schemas.AnswerRequest, db: Session = Depends(get_db)):
    if not request.question.strip():
        raise HTTPException(422, "Question must contain text")
    started = time.perf_counter()
    with search_timer(), measure_usage(request.quality) as usage:
        try:
            result = answer(request.question, Corpus.from_db(db), request.strategy, request.top_k)
        except (RuntimeError, ValueError, RedisError, OpenAIError):
            record_search("failed")
            raise HTTPException(503, "Answer generation unavailable; retry later or use BM25 search")
        record_search("success", len(result["citations"]))
    return {**result, "question": request.question, "strategy": request.strategy,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2), "usage": usage.to_dict()}
