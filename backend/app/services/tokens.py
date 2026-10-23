"""Token budgets use cl100k_base for the existing chat/embedding models.

If its vocabulary cannot be downloaded, UTF-8 bytes conservatively bound tokens.
Override the budget for models with different context windows/tokenizers.
"""
from functools import lru_cache
import tiktoken


@lru_cache(maxsize=1)
def encoding():
    try:
        return tiktoken.get_encoding("cl100k_base")
    except Exception:
        return None


def count(text: str) -> int:
    enc = encoding()
    return len(enc.encode(text, disallowed_special=())) if enc else len(text.encode("utf-8"))


def truncate(text: str, budget: int) -> str:
    if budget <= 0:
        return ""
    enc = encoding()
    if enc:
        return enc.decode(enc.encode(text, disallowed_special=())[:budget])
    return text.encode("utf-8")[:budget].decode("utf-8", errors="ignore")
