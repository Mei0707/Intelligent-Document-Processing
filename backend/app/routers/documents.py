import os
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from .. import models, schemas
from ..config import settings
from ..db import get_db
from ..pipeline import process_document
from ..services.vector_store import index

router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.post("", response_model=schemas.DocumentDetail, status_code=status.HTTP_201_CREATED)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File(...)],
    db: Session = Depends(get_db),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")

    contents = await file.read()
    size = len(contents)
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if size > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds max size of {settings.max_upload_mb} MB",
        )
    if size == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    ext = Path(file.filename).suffix
    stored_name = f"{uuid.uuid4().hex}{ext}"
    storage_path = settings.upload_path / stored_name
    storage_path.write_bytes(contents)

    doc = models.Document(
        filename=file.filename,
        storage_path=str(storage_path),
        mime_type=file.content_type or "application/octet-stream",
        size_bytes=size,
        status="pending",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    background_tasks.add_task(process_document, doc.id)
    return doc


@router.get("", response_model=schemas.DocumentList)
def list_documents(
    db: Session = Depends(get_db),
    category: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    q: str | None = Query(None, description="case-insensitive substring match on filename"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    query = db.query(models.Document)
    if category:
        query = query.filter(models.Document.category == category)
    if status_filter:
        query = query.filter(models.Document.status == status_filter)
    if q:
        query = query.filter(models.Document.filename.ilike(f"%{q}%"))

    total = query.count()
    items = (
        query.order_by(desc(models.Document.uploaded_at))
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {"items": items, "total": total}


@router.get("/{document_id}", response_model=schemas.DocumentDetail)
def get_document(document_id: int, db: Session = Depends(get_db)):
    doc = db.get(models.Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.get("/{document_id}/file")
def download_document(document_id: int, db: Session = Depends(get_db)):
    doc = db.get(models.Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if not os.path.exists(doc.storage_path):
        raise HTTPException(status_code=404, detail="File missing on disk")
    return FileResponse(doc.storage_path, media_type=doc.mime_type, filename=doc.filename)


@router.post("/{document_id}/reprocess", response_model=schemas.DocumentDetail)
def reprocess_document(
    document_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    doc = db.get(models.Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    # clear prior chunks so the new run starts clean
    db.query(models.Chunk).filter(models.Chunk.document_id == doc.id).delete()
    index.remove_document(doc.id)
    doc.status = "pending"
    doc.error = None
    db.commit()
    db.refresh(doc)
    background_tasks.add_task(process_document, doc.id)
    return doc


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: int, db: Session = Depends(get_db)):
    doc = db.get(models.Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        Path(doc.storage_path).unlink(missing_ok=True)
    except OSError:
        pass
    index.remove_document(doc.id)
    db.delete(doc)
    db.commit()
    return None
