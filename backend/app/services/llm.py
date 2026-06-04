"""Thin wrapper around the OpenAI client.

Centralizes the client construction so the API key is read once and every
caller gets consistent timeouts and model defaults.
"""

import json
from functools import lru_cache
from openai import OpenAI

from ..config import settings


@lru_cache(maxsize=1)
def _client() -> OpenAI:
    if not settings.openai_api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Copy backend/.env.example to backend/.env "
            "and add your key."
        )
    return OpenAI(api_key=settings.openai_api_key, timeout=60.0)


def chat_json(system: str, user: str, schema_hint: str | None = None) -> dict:
    """Call the chat model and parse a JSON response.

    Uses response_format=json_object so the model returns valid JSON.
    """
    instructions = system
    if schema_hint:
        instructions += f"\n\nRespond ONLY with a JSON object matching this shape:\n{schema_hint}"

    resp = _client().chat.completions.create(
        model=settings.openai_chat_model,
        messages=[
            {"role": "system", "content": instructions},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
    )
    content = resp.choices[0].message.content or "{}"
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {}


def chat_text(system: str, user: str, max_tokens: int = 400) -> str:
    resp = _client().chat.completions.create(
        model=settings.openai_chat_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.2,
        max_tokens=max_tokens,
    )
    return (resp.choices[0].message.content or "").strip()


def embed(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    resp = _client().embeddings.create(
        model=settings.openai_embedding_model,
        input=texts,
    )
    return [item.embedding for item in resp.data]
