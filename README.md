# Intelligent Document Processing Platform

An end-to-end MVP of the platform described in `proposal.docx`. Upload a
document (PDF / DOCX / TXT / image) and the backend automatically extracts
its text, classifies it, pulls structured fields, summarizes it, and embeds
it for semantic search. The React/MUI dashboard surfaces all of this and
lets you search the corpus with natural language.

## What's in the box

```
backend/                 FastAPI app
  app/
    main.py              app entrypoint + CORS + lifespan
    config.py            settings (env-driven)
    db.py                SQLAlchemy / SQLite setup
    models.py            Document + Chunk tables
    schemas.py           Pydantic response models
    pipeline.py          OCR → classify → extract → summarize → embed
    routers/
      documents.py       upload / list / detail / reprocess / delete
      search.py          semantic search endpoint
      analytics.py       dashboard stats
    services/
      ocr.py             PDF/DOCX/image/text extraction
      llm.py             OpenAI chat + embeddings wrapper
      classifier.py      6-category classifier
      extractor.py       category-aware field extraction
      summarizer.py      category-aware summarization
      embeddings.py      chunking + embedding
      vector_store.py    in-memory cosine index (pgvector stand-in)

frontend/                React + TypeScript + Material UI (Vite)
  src/
    main.tsx, App.tsx
    api.ts               typed axios client
    pages/
      Analytics.tsx      KPI cards + category chart + recent uploads
      Upload.tsx         drag-and-drop multi-file upload
      Documents.tsx      filterable table with live status polling
      DocumentDetail.tsx summary, extracted fields, raw text, file open
      Search.tsx         semantic search with example queries
    components/StatusChip.tsx
```

## Architecture notes

- **AI pipeline** runs in FastAPI `BackgroundTasks` — each upload returns
  immediately with `status: "pending"`, then the pipeline transitions the
  row to `processing → done` (or `failed`).
- **Vector store** is an in-memory NumPy cosine index hydrated from SQLite
  on startup. The `VectorIndex` interface (`hydrate / add / query / remove_document`)
  is a drop-in seam for pgvector / Pinecone / Weaviate later.
- **Models** default to `gpt-4o-mini` (chat) and `text-embedding-3-small`
  (embeddings) — both cheap and fast. Override with env vars.
- **Storage**: uploaded files land in `backend/uploads/<uuid><ext>`. Metadata,
  extracted fields, raw text, and chunk embeddings all live in SQLite at
  `backend/data/idp.db`.

## Running it locally

### 1. Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env and set OPENAI_API_KEY=sk-...
uvicorn app.main:app --reload --port 8000
```

The API is at <http://localhost:8000> and interactive docs at
<http://localhost:8000/docs>.

> **Image OCR (optional):** to OCR image uploads you also need the Tesseract
> binary installed locally (`brew install tesseract` on macOS). Without it,
> non-text files like PNGs will fail the pipeline with an "could not extract
> any text" error.

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. Vite proxies `/api/*` to the backend on 8000,
so no extra config is needed.

## Trying it out

1. Go to **Upload**, drop a PDF/DOCX/TXT in the drop zone.
2. Watch the row in **Documents** flip from `pending → processing → done`.
3. Click the row to see the summary, the category-specific extracted fields,
   and the raw extracted text.
4. Go to **Search** and try `Find invoices over $10,000` or any natural-language
   question — results come from the cosine-similarity index over chunk embeddings.
5. **Dashboard** shows KPI counts, a category bar chart, and the latest uploads.

## API endpoints

| Method | Path                                  | Description                            |
| ------ | ------------------------------------- | -------------------------------------- |
| POST   | `/api/documents`                      | Multipart upload, queues pipeline      |
| GET    | `/api/documents`                      | List with `category` / `status` / `q`  |
| GET    | `/api/documents/{id}`                 | Full document detail                   |
| GET    | `/api/documents/{id}/file`            | Download the original file             |
| POST   | `/api/documents/{id}/reprocess`       | Re-run the pipeline                    |
| DELETE | `/api/documents/{id}`                 | Delete document + chunks               |
| GET    | `/api/search?q=...&top_k=10`          | Semantic search                        |
| GET    | `/api/analytics`                      | Dashboard counts + recent uploads      |
| GET    | `/api/health`                         | Liveness check                         |

## What this MVP intentionally leaves out

The proposal calls for Postgres + pgvector, Redis-backed worker queues,
Docker Compose, auth, CloudWatch/Grafana, and 500-concurrent-user scaling.
This MVP ships the AI pipeline and full UX surface in a form that runs on a
laptop without external services. Lifting to production means:

- Swap SQLite → Postgres (change `DATABASE_URL` only).
- Swap `VectorIndex` → pgvector or Pinecone (keep the same interface).
- Move `process_document` from FastAPI `BackgroundTasks` → an RQ/Celery
  worker fed by Redis, so uploads can scale horizontally.
- Add an auth layer (FastAPI dependency + JWT) in front of the routers.
- Containerize with the included `requirements.txt` / `package.json` and
  wire CloudWatch or Prometheus around the worker + API.
