"""Compute document outputs outside transactions; atomically publish under a lease."""
from pathlib import Path
from datetime import datetime
from sqlalchemy import update, delete
from . import models
from .db import SessionLocal
from .config import settings
from .jobs import LeaseLost, PermanentJobError, owned, renew
from .monitoring import pipeline_stage, record_document_chunks, record_document_processing
from .services import ocr, classifier, extractor, summarizer, embeddings, tokens


def process_document(document_id: int, job_id: str, lease_token: str) -> None:
    with SessionLocal() as db:
        doc = db.get(models.Document, document_id)
        if doc is None:
            raise FileNotFoundError("Document no longer exists")
        path, mime_type = doc.storage_path, doc.mime_type

    def stage(name, function, *args):
        renew(job_id, lease_token, name)
        with pipeline_stage(name):
            return function(*args)

    text = stage("ocr", ocr.extract_text, Path(path), mime_type)
    if not text or not text.strip():
        raise PermanentJobError("Could not extract any text from the file")
    token_count = tokens.count(text)
    if token_count > settings.max_document_tokens:
        raise PermanentJobError("Document exceeds MAX_DOCUMENT_TOKENS; split it into smaller files")
    cls = stage("classification", classifier.classify, text)
    fields = stage("field_extraction", extractor.extract_fields, text, cls["category"])
    summary = stage("summary", summarizer.summarize, text, cls["category"])
    chunks = stage("chunking", embeddings.chunk_text, text)
    vectors = stage("embedding", embeddings.embed_chunks, chunks)
    if len(vectors) != len(chunks):
        raise ValueError("Chunk and vector counts differ")
    # The conditional UPDATE locks the job before replacing chunks/document output.
    # A worker whose lease expired can never overwrite a newer worker's result.
    with SessionLocal() as db:
        changed = db.execute(update(models.ProcessingJob).where(owned(job_id, lease_token)).values(
            status="succeeded", stage="done", lease_token=None, lease_until=None, updated_at=datetime.utcnow(),
        )).rowcount
        if not changed:
            raise LeaseLost("Lease expired before commit")
        db.execute(delete(models.Chunk).where(models.Chunk.document_id == document_id))
        for i, (chunk, vector) in enumerate(zip(chunks, vectors)):
            db.add(models.Chunk(document_id=document_id, chunk_index=i, text=chunk, embedding=vector))
        doc = db.get(models.Document, document_id)
        doc.raw_text, doc.token_count = text, token_count
        doc.category, doc.category_confidence = cls["category"], cls["confidence"]
        doc.extracted_fields, doc.summary = fields, summary
        doc.status, doc.error = "done", None
        db.commit()
    record_document_chunks(cls["category"], len(chunks))
    record_document_processing("success", cls["category"])
