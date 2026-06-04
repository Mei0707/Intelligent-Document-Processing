from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..db import get_db
from ..services import llm
from ..services.vector_store import index

router = APIRouter(prefix="/api/search", tags=["search"])


def _snippet(text: str, max_chars: int = 280) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= max_chars else text[: max_chars - 1].rstrip() + "…"


@router.get("", response_model=schemas.SearchResponse)
def search(
    q: str = Query(..., min_length=1, description="natural-language query"),
    top_k: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    try:
        q_vec = llm.embed([q])[0]
    except RuntimeError as e:
        # missing API key etc.
        raise HTTPException(status_code=503, detail=str(e))

    raw = index.query(q_vec, top_k=top_k)
    hits: list[schemas.SearchHit] = []
    for entry, score in raw:
        doc = db.get(models.Document, entry.document_id)
        if doc is None:
            continue
        hits.append(
            schemas.SearchHit(
                document_id=doc.id,
                filename=doc.filename,
                category=doc.category,
                snippet=_snippet(entry.text),
                score=round(score, 4),
            )
        )
    return {"query": q, "hits": hits}
