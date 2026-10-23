"""Token-bounded, overlapping chunks preserving exact source text for citations."""
from ..config import settings
from . import llm, tokens


def chunk_text(text: str, chunk_size: int | None = None, overlap: int | None = None) -> list[str]:
    size = settings.chunk_tokens if chunk_size is None else chunk_size
    overlap = settings.chunk_overlap_tokens if overlap is None else overlap
    if size <= 0 or overlap < 0 or overlap >= size:
        raise ValueError("Require chunk_size > overlap >= 0")
    text = (text or "").strip()
    chunks, start = [], 0
    while start < len(text):
        # Binary search characters, avoiding token-decode splits inside Unicode.
        low, high = start + 1, min(len(text), start + size * 8)
        end = start
        while low <= high:
            mid = (low + high) // 2
            if tokens.count(text[start:mid]) <= size:
                end, low = mid, mid + 1
            else:
                high = mid - 1
        if end == start:
            raise ValueError("Chunk budget cannot hold a single character")
        if end < len(text):
            boundary = max(text.rfind("\n\n", start, end), text.rfind(". ", start, end))
            if boundary > start + (end - start) // 2:
                end = boundary + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(text):
            break
        # Find an exact source suffix within overlap token budget.
        low, high, suffix = start + 1, end, end
        while low <= high:
            mid = (low + high) // 2
            if tokens.count(text[mid:end]) <= overlap:
                suffix, high = mid, mid - 1
            else:
                low = mid + 1
        start = max(start + 1, suffix)
    return chunks


def embed_chunks(chunks):
    return llm.embed(chunks)
