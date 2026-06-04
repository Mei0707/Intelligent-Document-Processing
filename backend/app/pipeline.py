"""End-to-end processing pipeline for a single uploaded document.

Runs as a background task. Updates the Document row through each stage so
the UI can show progress. Any per-stage failure marks the document failed
but leaves whatever earlier stages produced intact.
"""

import logging
from pathlib import Path

from sqlalchemy.orm import Session

from . import models
from .db import SessionLocal
from .services import ocr, classifier, extractor, summarizer, embeddings
from .services.vector_store import index

log = logging.getLogger("idp.pipeline")


def process_document(document_id: int) -> None:
    """Run the full pipeline. Opens its own DB session so it's safe to call
    from FastAPI's BackgroundTasks (which runs after the request session closes)."""
    db: Session = SessionLocal()
    try:
        doc = db.get(models.Document, document_id)
        if doc is None:
            log.warning("process_document: id=%s not found", document_id)
            return

        doc.status = "processing"
        doc.error = None
        db.commit()

        try:
            # 1. OCR / text extraction
            text = ocr.extract_text(Path(doc.storage_path), doc.mime_type)
            doc.raw_text = text
            doc.token_count = len(text.split()) if text else 0
            db.commit()

            if not text or not text.strip():
                doc.status = "failed"
                doc.error = "Could not extract any text from the file."
                db.commit()
                return

            # 2. Classification
            cls = classifier.classify(text)
            doc.category = cls["category"]
            doc.category_confidence = cls["confidence"]
            db.commit()

            # 3. Field extraction
            doc.extracted_fields = extractor.extract_fields(text, doc.category)
            db.commit()

            # 4. Summary
            doc.summary = summarizer.summarize(text, doc.category)
            db.commit()

            # 5. Chunk + embed + index
            chunks = embeddings.chunk_text(text)
            if chunks:
                vectors = embeddings.embed_chunks(chunks)
                # persist chunks
                rows: list[tuple[int, int, str, list[float]]] = []
                for i, (chunk_text, vec) in enumerate(zip(chunks, vectors)):
                    row = models.Chunk(
                        document_id=doc.id,
                        chunk_index=i,
                        text=chunk_text,
                        embedding=vec,
                    )
                    db.add(row)
                db.flush()
                # collect ids for the in-memory index
                db.refresh(doc)
                for c in doc.chunks:
                    rows.append((c.id, doc.id, c.text, list(c.embedding)))
                db.commit()
                index.add(rows)

            doc.status = "done"
            db.commit()
        except Exception as e:  # any per-stage failure
            log.exception("Pipeline failed for document %s", document_id)
            doc.status = "failed"
            doc.error = f"{type(e).__name__}: {e}"[:500]
            db.commit()
    finally:
        db.close()
