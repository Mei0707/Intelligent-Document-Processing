"""Chunking + embedding helpers."""

from . import llm


def chunk_text(text: str, chunk_size: int = 1200, overlap: int = 150) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + chunk_size, n)
        # try to break on a paragraph or sentence boundary near `end`
        if end < n:
            window = text.rfind("\n\n", start, end)
            if window == -1 or window < start + chunk_size // 2:
                window = text.rfind(". ", start, end)
            if window != -1 and window > start + chunk_size // 2:
                end = window + 1
        chunks.append(text[start:end].strip())
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return [c for c in chunks if c]


def embed_chunks(chunks: list[str]) -> list[list[float]]:
    if not chunks:
        return []
    return llm.embed(chunks)
