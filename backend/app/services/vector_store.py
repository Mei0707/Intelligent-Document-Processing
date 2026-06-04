"""In-memory cosine-similarity index, hydrated from SQLite on startup.

This stands in for pgvector/Pinecone for the MVP. Production would swap
this module for a real vector DB while keeping the same `query` interface.
"""

from dataclasses import dataclass
from threading import RLock
import numpy as np

from sqlalchemy.orm import Session

from .. import models


@dataclass
class _Entry:
    chunk_id: int
    document_id: int
    text: str
    vector: np.ndarray  # unit-normalized


class VectorIndex:
    def __init__(self) -> None:
        self._entries: list[_Entry] = []
        self._matrix: np.ndarray | None = None
        self._lock = RLock()

    def _rebuild_matrix(self) -> None:
        if not self._entries:
            self._matrix = None
            return
        self._matrix = np.stack([e.vector for e in self._entries])

    @staticmethod
    def _normalize(v: list[float] | np.ndarray) -> np.ndarray:
        arr = np.asarray(v, dtype=np.float32)
        n = np.linalg.norm(arr)
        return arr if n == 0 else arr / n

    def hydrate(self, db: Session) -> None:
        with self._lock:
            self._entries.clear()
            for chunk in db.query(models.Chunk).all():
                if not chunk.embedding:
                    continue
                self._entries.append(
                    _Entry(
                        chunk_id=chunk.id,
                        document_id=chunk.document_id,
                        text=chunk.text,
                        vector=self._normalize(chunk.embedding),
                    )
                )
            self._rebuild_matrix()

    def add(self, chunks: list[tuple[int, int, str, list[float]]]) -> None:
        """chunks: list of (chunk_id, document_id, text, embedding)."""
        if not chunks:
            return
        with self._lock:
            for cid, did, text, vec in chunks:
                self._entries.append(
                    _Entry(
                        chunk_id=cid,
                        document_id=did,
                        text=text,
                        vector=self._normalize(vec),
                    )
                )
            self._rebuild_matrix()

    def remove_document(self, document_id: int) -> None:
        with self._lock:
            self._entries = [e for e in self._entries if e.document_id != document_id]
            self._rebuild_matrix()

    def query(self, query_vec: list[float], top_k: int = 5) -> list[tuple[_Entry, float]]:
        with self._lock:
            if self._matrix is None or not self._entries:
                return []
            q = self._normalize(query_vec)
            sims = self._matrix @ q  # cosine since both sides are unit-norm
            # take top_k document-best chunks (dedupe per document)
            order = np.argsort(-sims)
            seen: set[int] = set()
            results: list[tuple[_Entry, float]] = []
            for idx in order:
                entry = self._entries[int(idx)]
                if entry.document_id in seen:
                    continue
                seen.add(entry.document_id)
                results.append((entry, float(sims[int(idx)])))
                if len(results) >= top_k:
                    break
            return results


index = VectorIndex()
