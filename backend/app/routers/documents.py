import os
import hashlib
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import desc, update
from datetime import datetime
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models, schemas, jobs
from ..config import settings
from ..db import get_db
from ..monitoring import record_document_upload

router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.post("", response_model=schemas.DocumentDetail, status_code=status.HTTP_201_CREATED)
def upload_document(
    file: Annotated[UploadFile, File(...)],
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(None, max_length=128),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")

    max_bytes = settings.max_upload_mb * 1024 * 1024
    contents = file.file.read(max_bytes + 1)
    size = len(contents)
    if size > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds max size of {settings.max_upload_mb} MB",
        )
    if size == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    fingerprint = hashlib.sha256(contents + b"\0" + file.filename.encode()).hexdigest()
    if idempotency_key:
        existing = db.query(models.ProcessingJob).filter_by(idempotency_key=idempotency_key).first()
        if existing:
            if existing.content_hash != fingerprint:
                raise HTTPException(409, "Idempotency key was already used for different content")
            return db.get(models.Document, existing.document_id)

    mime_type = file.content_type or "application/octet-stream"
    ext = Path(file.filename).suffix
    stored_name = f"{uuid.uuid4().hex}{ext}"
    storage_path = settings.upload_path / stored_name
    storage_path.write_bytes(contents)
    record_document_upload(mime_type, size)

    doc = models.Document(
        filename=file.filename,
        storage_path=str(storage_path),
        mime_type=mime_type,
        size_bytes=size,
        status="pending",
    )
    db.add(doc)
    try:
        db.flush()
        jobs.create_job(db, doc, fingerprint, idempotency_key)
        db.commit()
    except IntegrityError:
        db.rollback()
        storage_path.unlink(missing_ok=True)
        existing = db.query(models.ProcessingJob).filter_by(idempotency_key=idempotency_key).first() if idempotency_key else None
        if existing and existing.content_hash == fingerprint:
            return db.get(models.Document, existing.document_id)
        raise HTTPException(409, "Conflicting idempotency key")
    except Exception:
        db.rollback()
        storage_path.unlink(missing_ok=True)
        raise
    db.refresh(doc)
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
    db: Session = Depends(get_db),
):
    doc = db.get(models.Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.job:
        jobs.reset_job(db, doc.job)
    else:
        # Adopt documents uploaded before durable jobs were introduced.
        jobs.create_job(db, doc, hashlib.sha256(Path(doc.storage_path).read_bytes()).hexdigest())
        doc.status = "pending"
        doc.error = None
    db.commit()
    db.refresh(doc)
    return doc


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: int, db: Session = Depends(get_db)):
    doc = db.get(models.Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.job:
        # Lock in the same job -> document order as claim/reset/final publication.
        # A concurrent replay cannot turn this into deletion of an active job.
        guarded = db.execute(update(models.ProcessingJob).where(
            models.ProcessingJob.id == doc.job.id,
            models.ProcessingJob.status.notin_(jobs.ACTIVE)
        ).values(updated_at=datetime.utcnow())).rowcount
        if not guarded:
            db.rollback()
            raise HTTPException(409, "Wait for the active processing job before deleting")
    path = Path(doc.storage_path)
    db.delete(doc)
    db.commit()
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
    return None


@router.get("/{document_id}/chunks/{chunk_id}")
def get_chunk(document_id: int, chunk_id: int, digest: str | None = None, db: Session = Depends(get_db)):
    chunk = db.query(models.Chunk).filter_by(id=chunk_id, document_id=document_id).first()
    if not chunk:
        raise HTTPException(404, "Source chunk no longer exists; the document may have been reprocessed")
    if digest and hashlib.sha256(chunk.text.encode()).hexdigest() != digest:
        raise HTTPException(410, "Source changed after this answer was generated")
    return {"document_id": document_id, "chunk_id": chunk.id, "chunk_index": chunk.chunk_index, "text": chunk.text}


@router.get("/{document_id}/job", response_model=schemas.JobResponse)
def document_job(document_id: int, db: Session = Depends(get_db)):
    job = db.query(models.ProcessingJob).filter_by(document_id=document_id).first()
    if not job:
        raise HTTPException(404, "No processing job found")
    return job
