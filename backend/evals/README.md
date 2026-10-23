# Accuracy Evaluation

This folder contains a lightweight evaluation harness for the current document
classifier and structured-field extractor.

Run it from the project root:

```bash
python -m evals.accuracy
```

Or run it from the backend directory:

```bash
cd backend
python -m evals.accuracy
```

It uses `evals/accuracy_dataset.json` by default and requires `OPENAI_API_KEY`
because it calls the real LLM-backed services. A larger synthetic dataset is
available at `evals/accuracy_dataset_large.json`.

Useful variants:

```bash
python -m evals.accuracy --skip-extraction
python -m evals.accuracy --json
python -m evals.accuracy --min-classification-accuracy 0.90 --min-field-accuracy 0.85
python -m evals.accuracy --dataset path/to/your_labeled_dataset.json
python -m evals.accuracy --dataset backend/evals/accuracy_dataset_large.json
```

The included datasets are synthetic. The small dataset is a starter smoke
benchmark, and the large dataset gives a broader development signal. Do not use
either to claim production accuracy. For a defensible number, replace or extend
them with representative labeled documents from the real workflow.

Each dataset item should have:

```json
{
  "id": "stable_example_id",
  "expected_category": "Invoice",
  "text": "document text to evaluate",
  "expected_fields": {
    "invoice_number": "INV-1007",
    "total_amount": 4700
  }
}
```

The report measures:

- Classification accuracy: predicted category equals `expected_category`.
- Field extraction accuracy: exact normalized match for each expected field.

Summaries and semantic search are not scored here because they need separate
human-rated or retrieval-quality benchmarks.

## RAG and inference benchmarking

The RAG runner lives in `rag.py` with labeled `rag_dataset.json`. Run
`python -m evals.rag --offline --k 3` for a provider-free retrieval smoke test.
Run `python -m evals.rag --answers --extraction --k 3 --repeats 3 --output report.json`
with configured OpenAI + Redis to measure real retrieval, answers, fields,
latency, provider tokens, and configured token prices. Compare routes with
`--qualities balanced high`, budgets with `--context-tokens`, and response-cache
tradeoffs with `--cache warm --repeats 3`.

Metrics, test-set limits, exact scoring semantics, and operating instructions
are documented in `../../docs/architecture.md` and the project README. Offline
fixture vectors do not measure semantic embedding or generated-answer quality.
