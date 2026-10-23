"""Bounded inference, task-based routing, response cache and measured API usage."""
import hashlib
import json
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from functools import lru_cache
from redis.exceptions import RedisError
from openai import OpenAI
from ..config import settings
from ..monitoring import LLM_SECONDS, LLM_CALLS, LLM_TOKENS, LLM_COST, CACHE_HITS
from ..telemetry import span
from .redis_client import redis_client
from . import tokens


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    response_cache_hits: int = 0
    calls: int = 0
    estimated_cost_usd: float = 0.0
    cost_known: bool = True

    def to_dict(self):
        result = asdict(self)
        if not self.cost_known:
            result["estimated_cost_usd"] = None
        return result


_usage: ContextVar[Usage | None] = ContextVar("llm_usage", default=None)
_route: ContextVar[str] = ContextVar("llm_route", default="balanced")


class InferenceBusy(RuntimeError):
    """Capacity backpressure, rather than a provider or document failure."""


@contextmanager
def measure_usage(quality="balanced"):
    usage = Usage()
    usage_token = _usage.set(usage)
    route_token = _route.set(quality)
    try:
        yield usage
    finally:
        _usage.reset(usage_token)
        _route.reset(route_token)


@lru_cache(maxsize=1)
def _client():
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    return OpenAI(api_key=settings.openai_api_key, timeout=settings.llm_timeout_seconds, max_retries=0)


def model_for(task):
    if _route.get() == "high" and settings.complex_model:
        return settings.complex_model
    if task == "answer" and settings.answer_model:
        return settings.answer_model
    return settings.openai_chat_model


# Global leases bound inference across API processes and worker pools. An expired
# permit cannot survive a worker crash. Timeout exceeds the single SDK request.
_ACQUIRE = """
local clock = redis.call('TIME')
local now = tonumber(clock[1]) + tonumber(clock[2]) / 1000000
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now)
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[2]) then return 0 end
redis.call('ZADD', KEYS[1], now + tonumber(ARGV[1]), ARGV[3])
redis.call('EXPIRE', KEYS[1], ARGV[1])
return 1
"""


@contextmanager
def inference_slot():
    client = redis_client()
    permit = uuid.uuid4().hex
    ttl = int(settings.llm_timeout_seconds) + 30
    if not client.eval(_ACQUIRE, 1, "idp:llm:permits", ttl, settings.llm_concurrency, permit):
        raise InferenceBusy("Inference concurrency limit reached; retry later")
    try:
        yield
    finally:
        try:
            client.zrem("idp:llm:permits", permit)
        except RedisError:
            pass  # bounded permit expires automatically


def _record(model, operation, response):
    usage = getattr(response, "usage", None)
    inp = getattr(usage, "prompt_tokens", 0) or 0
    out = getattr(usage, "completion_tokens", 0) or 0
    details = getattr(usage, "prompt_tokens_details", None)
    cached = getattr(details, "cached_tokens", 0) or 0
    prices = settings.model_prices.get(model)
    cost = None
    if usage is not None and prices and "input" in prices and (operation == "embed" or "output" in prices):
        cost = ((inp - cached) * prices["input"] + cached * prices.get("cached_input", prices["input"])
                + out * prices.get("output", 0)) / 1_000_000
        LLM_COST.labels(model).inc(cost)
    current = _usage.get()
    if current:
        current.input_tokens += inp
        current.output_tokens += out
        current.cached_tokens += cached
        current.calls += 1
        current.cost_known &= cost is not None
        current.estimated_cost_usd += cost or 0
    for kind, amount in (("input", inp), ("output", out), ("cached_input", cached)):
        LLM_TOKENS.labels(model, kind).inc(amount)


def _cached_call(operation, model, payload, execute):
    key = "idp:inference:v1:" + hashlib.sha256(
        json.dumps([operation, model, payload], sort_keys=True).encode()).hexdigest()
    if settings.cache_ttl_seconds:
        try:
            value = redis_client().get(key)
            if value is not None:
                CACHE_HITS.labels(operation).inc()
                current = _usage.get()
                if current:
                    current.response_cache_hits += 1
                return json.loads(value)
        except (RedisError, ValueError):
            pass
    started = time.perf_counter()
    outcome = "error"
    try:
        with span("llm." + operation, model=model), inference_slot():
            response, value = execute()
            outcome = "success"
        if settings.cache_ttl_seconds:
            try:
                redis_client().setex(key, settings.cache_ttl_seconds, json.dumps(value))
            except RedisError:
                pass
        return value
    except InferenceBusy:
        outcome = "capacity_limited"
        raise
    finally:
        LLM_CALLS.labels(model, operation, outcome).inc()
        LLM_SECONDS.labels(model, operation).observe(time.perf_counter() - started)


def _chat(system, user, max_tokens, task, json_mode, output_schema=None):
    model = model_for(task)
    payload = dict(messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                   temperature=0.1, max_tokens=min(max_tokens, settings.llm_output_tokens))
    if output_schema:
        payload["response_format"] = {"type": "json_schema", "json_schema": {
            "name": task + "_response", "strict": True, "schema": output_schema}}
    elif json_mode:
        payload["response_format"] = {"type": "json_object"}
    schema_tokens = tokens.count(json.dumps(payload.get("response_format", {})))
    input_tokens = tokens.count(system) + tokens.count(user) + schema_tokens + 32
    if input_tokens > settings.llm_input_tokens:
        raise ValueError("Prompt exceeds input token budget; reduce retrieved context or document input")

    def execute():
        response = _client().chat.completions.create(model=model, **payload)
        _record(model, task, response)
        if response.choices[0].finish_reason == "length":
            raise ValueError("Model output exceeded output token budget")
        content = response.choices[0].message.content or ""
        value = json.loads(content) if json_mode else content.strip()
        if json_mode and not isinstance(value, dict):
            raise ValueError("Expected a JSON object from model")
        return response, value
    return _cached_call(task, model, payload, execute)


def chat_json(system, user, schema_hint=None, *, task="extract", max_tokens=None, output_schema=None):
    if schema_hint:
        system += f"\nRespond ONLY with JSON matching this shape:\n{schema_hint}"
    return _chat(system, user, max_tokens or settings.llm_output_tokens, task, True, output_schema)


def chat_text(system, user, max_tokens=400, *, task="summary"):
    return _chat(system, user, max_tokens, task, False)


def embed(texts):
    if not texts:
        return []
    batches, batch, size = [], [], 0
    for text in texts:
        n = tokens.count(text)
        if n > 8191 or not text.strip():
            raise ValueError("Embedding input must be nonempty and at most 8191 tokens")
        if batch and (len(batch) >= settings.embedding_batch_size or size + n > settings.embedding_batch_tokens):
            batches.append(batch)
            batch, size = [], 0
        batch.append(text)
        size += n
    if batch:
        batches.append(batch)
    vectors = []
    for batch in batches:
        def execute(batch=batch):
            response = _client().embeddings.create(model=settings.openai_embedding_model, input=batch)
            _record(settings.openai_embedding_model, "embed", response)
            ordered = sorted(response.data, key=lambda item: item.index)
            if len(ordered) != len(batch):
                raise ValueError("Embedding response count does not match inputs")
            return response, [item.embedding for item in ordered]
        vectors.extend(_cached_call("embed", settings.openai_embedding_model, batch, execute))
    return vectors
