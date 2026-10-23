# Intelligent Document Processing Platform

Upload PDF, DOCX, text, or image files, then classify them, extract structured
fields, summarize them, and ask questions with document citations. FastAPI and
SQLAlchemy serve the API; React, TypeScript, and Material UI provide the dashboard.
Redis workers process documents independently of HTTP requests.

## Run locally

```bash
cp -n backend/.env.example backend/.env
# Set OPENAI_API_KEY in backend/.env. Merge new settings from .env.example into an existing .env.
docker compose up --build
```

This starts the API, Redis with AOF persistence, a bounded worker pool, Prometheus,
Grafana, and Tempo. API: <http://localhost:8000/docs>. Grafana:
<http://localhost:3000> (local default `admin` / `admin`; override
`GRAFANA_ADMIN_PASSWORD`). Prometheus: <http://localhost:9090>.

Run the frontend separately:

```bash
cd frontend
npm ci
npm run dev
```

Open <http://localhost:5173>. Vite proxies `/api` to port 8000. Docker uses named
volumes for documents and SQLite; it does not import an existing local database.
Do not remove volumes if you need to retain uploaded documents.

Alternatively, run Python services directly. Both processes **must** use the
same working directory, database, and upload path:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# Start Redis (docker compose up -d redis), then in separate terminals:
uvicorn app.main:app --reload --port 8000
python -m app.worker
```

Image OCR needs the Tesseract binary (`brew install tesseract` on macOS); the
backend Docker image includes it. Scanned PDFs currently need OCR preprocessing.
For host-based Python services, the optional monitoring stack can run with
`docker compose -f monitoring/docker-compose.yml up`; set
`OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318` for traces.

## Retrieval and cited answers

Documents are split into token-bounded, overlapping passages and embedded in
bounded batches. Embeddings and text are persisted in SQL. Search loads a
consistent snapshot of completed documents, so worker output is visible without
restarting or hydrating API process memory.

Choose **BM25**, **vector**, **hybrid**, or **hybrid + reranking** in Search.
Hybrid search uses reciprocal rank fusion and is the default strategy. The optional LLM reranker scores candidate
passages in one batch with a strict score schema; `RERANKER=lexical` selects a cheaper,
deterministic term-coverage reranker. BM25 source search works without an API key.

Answers use only the retrieved context. Every accepted claim includes server-built
citation markers, document/chunk identifiers, source links, and exact quotations.
Unknown chunk IDs or fabricated quotes are rejected. Questions without usable
evidence receive an explicit abstention. Source URLs include content digests to
detect reprocessing. Citations identify passages, not PDF page numbers.

## Reliable jobs

Uploads and durable job rows commit together, before the HTTP response. A worker
publishes SQL outbox rows to Redis Streams and executes them in a bounded pool.
A Redis outage leaves accepted work in the outbox. Database leases, heartbeats,
and fenced final commits protect against duplicate delivery and crashed workers.
Outputs and replacement chunks commit atomically.

Jobs retry with exponential backoff and jitter. Exhausted or permanently invalid
jobs enter the SQL dead-letter ledger and Redis dead-letter stream. Inspect
`GET /api/jobs/{id}` and replay with `POST /api/jobs/{id}/retry` or the document's
**Reprocess** button. The document detail page shows stage, state, and attempt count.
Send `Idempotency-Key` on upload to deduplicate client retries; reusing a key for
different bytes/filename returns 409. Reprocess requests while active are coalesced.

## Inference controls

- Redis response/embedding cache with TTL and model-specific hashed keys.
- Stable system prompts precede variable content for provider prompt caching;
  actual provider cached-token usage is recorded.
- Explicit input/output/context/document token budgets and embedding batch limits.
- Redis-backed inference concurrency permits shared across API and worker processes.
- Separate answer and optional high-quality model routes (`ANSWER_MODEL`,
  `COMPLEX_MODEL`); unset routes use the existing chat model.
- Measured input/output tokens and configurable per-model prices. Unknown pricing
  is reported as `null`, never as a measured zero cost.

See [configuration](backend/.env.example). The integration retains the existing
`gpt-4o-mini` and `text-embedding-3-small` defaults; configure model IDs supported by
your account. Chat routes must support JSON mode, strict JSON Schema, temperature, and `max_tokens`.

## Evaluation and verification

```bash
cd backend
pip install -r requirements-dev.txt
python -m unittest discover -s tests -v

# No provider calls: lexical fixture vectors test retrieval plumbing only.
python -m evals.rag --offline --k 3 --output ../docs/benchmarks/offline.json

# Real embeddings, reranking, answers, and extraction; requires key + Redis.
python -m evals.rag --answers --extraction --k 3 --repeats 3 \
  --output ../docs/benchmarks/live.json

# Compare routing, context budgets, and application-cache effects.
python -m evals.rag --answers --qualities balanced high --context-tokens 3000 \
  --cache warm --repeats 3 --output ../docs/benchmarks/routes.json

# Original classifier/extractor datasets remain available.
python -m evals.accuracy --json
```

The labeled RAG dataset contains eight documents and eleven questions, including
exact IDs, distractors, multiple relevant documents, and an unanswerable question.
Reports include Recall@K, MRR@K, labeled answer correctness, token F1, citation
precision, extraction accuracy, p50/p95 latency, errors, provider tokens, and
estimated cost. The recorded [live/cache baseline](docs/benchmark-baseline.md) compares the measured tradeoffs. Answer correctness requires all labeled facts and relevant-document
citations; it is an automated regression score, not a semantic correctness proof.
Replace synthetic development examples with held-out domain labels before choosing
models for production. Offline reports leave answer/extraction quality unmeasured.

Use `--min-recall` and `--min-answer-correctness` for regression gates; provider
errors fail evaluation. `--cache cold` disables the application cache, but cannot
turn off provider-managed prompt caching. Run integration tests with
`TEST_REDIS_URL=redis://localhost:16379/15` to use a disposable real Redis database
instead of fakeredis; this mode clears database 15.

## Observability

API metrics are at `/metrics`; worker metrics are at port 8001. Grafana provisions
API/job/retrieval/LLM p50/p95 latency, error rates, job states, queue wait/depth,
provider tokens, cache hits, retries, and estimated cost. OpenTelemetry traces
connect upload requests to worker pipeline stages, retrieval, and inference;
Grafana's Tempo datasource supports trace exploration. Spans exclude document text
and prompts. Prometheus alert rules cover worker availability, dead letters, queue
backlog, and inference errors; notification routing is deployment-specific.

## API

| Method | Path | Behavior |
| --- | --- | --- |
| POST | `/api/documents` | Upload + durable job; returns document and job ID |
| GET | `/api/documents` | Filter by category, status, or filename |
| GET | `/api/documents/{id}` | Summary, fields, raw text, job ID |
| GET | `/api/documents/{id}/file` | Original document |
| GET | `/api/documents/{id}/job` | Current processing state |
| GET | `/api/documents/{id}/chunks/{chunk_id}` | Cited source passage |
| POST | `/api/documents/{id}/reprocess` | Queue atomic replacement processing |
| DELETE | `/api/documents/{id}` | Delete inactive document and outputs |
| GET | `/api/jobs/{id}` | Status, stage, attempts, error |
| POST | `/api/jobs/{id}/retry` | Replay dead-letter job |
| GET | `/api/search?q=...&strategy=hybrid` | Ranked passages |
| POST | `/api/search/answer` | Grounded answer, citations, usage, latency |
| GET | `/api/analytics` | Dashboard statistics |
| GET | `/api/health` | Liveness |
| GET | `/metrics` | Prometheus API metrics |

An answer request is `{"question":"When is payment due?","strategy":"hybrid",
"top_k":5,"quality":"balanced"}`. See OpenAPI for complete schemas.

## Project map and operating limits

[Architecture and operations](docs/architecture.md) explains transactions, recovery,
ranking, evaluation, and limits. SQL stores exact vectors as JSON; retrieval scans
the completed corpus and targets small deployments. Large corpora need an ANN
backend such as pgvector, plus indexed lexical retrieval. SQLite WAL supports the
local worker pool; multi-host deployments should use PostgreSQL and shared object
storage. Authentication, tenant isolation, and PDF page-coordinate citations are
outside this change. The original in-memory `vector_store.py` remains for compatibility
but is no longer used by API search or workers.
