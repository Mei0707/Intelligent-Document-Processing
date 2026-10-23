"""Reproducible retrieval/answer/field evaluation; never touches the application DB."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time
import numpy as np
from app.config import settings
from app.services import embeddings, llm, classifier, extractor
from app.services.retrieval import Candidate, Corpus, STRATEGIES, retrieve, terms
from app.services.rag import generate_answer
from .accuracy import score_fields

DEFAULT_DATASET = Path(__file__).with_name("rag_dataset.json")


def load_dataset(path):
    data = json.loads(Path(path).read_text())
    docs, queries = data.get("documents", []), data.get("queries", [])
    ids = [d["id"] for d in docs]
    qids = [q["id"] for q in queries]
    if not docs or not queries or len(set(ids)) != len(ids) or len(set(qids)) != len(qids):
        raise ValueError("Dataset requires nonempty documents/queries with unique IDs")
    for d in docs:
        if not d.get("text", "").strip():
            raise ValueError("Document text must be nonempty")
    for q in queries:
        relevant = q.get("relevant_document_ids", [])
        if not q.get("question", "").strip() or not set(relevant) <= set(ids):
            raise ValueError("Invalid question or unknown relevance label")
        if not relevant and not q.get("unanswerable"):
            raise ValueError("Empty relevance labels require unanswerable=true")
        if not q.get("unanswerable") and not q.get("required_facts"):
            raise ValueError("Answerable questions require required_facts labels")
    return data


def retrieval_metrics(document_ids, relevant_ids, k):
    # K counts passages. Multiple passages from the same document earn credit once.
    ranked = document_ids[:k]
    relevant = set(relevant_ids)
    if not relevant:
        return {"recall_at_k": None, "mrr": None}
    recall = len(set(ranked) & relevant) / len(relevant)
    reciprocal = next((1 / rank for rank, did in enumerate(ranked, 1) if did in relevant), 0)
    return {"recall_at_k": recall, "mrr": reciprocal}


def normalized(text):
    return " ".join(re.findall(r"\w+", re.sub(r"\[\d+\]", "", text.lower())))


def answer_metrics(result, example):
    if example.get("unanswerable"):
        return {"answer_correctness": float(result["abstained"]), "answer_token_f1": float(result["abstained"]),
                "fact_coverage": None, "citation_precision": None}
    text = normalized(result["answer"])
    # Labels are groups of accepted aliases, not a model judging its own output.
    facts = example["required_facts"]
    coverage = sum(any(re.search(r"(?<!\w)" + re.escape(normalized(alias)) + r"(?!\w)", text)
                       for alias in aliases) for aliases in facts) / len(facts)
    expected, actual = Counter(normalized(example["reference_answer"]).split()), Counter(text.split())
    overlap = sum((expected & actual).values())
    f1 = 2 * overlap / max(1, sum(expected.values()) + sum(actual.values()))
    citations = result.get("citations", [])
    precision = (sum(c["document_id"] in example["relevant_document_ids"] for c in citations) / len(citations)) if citations else 0
    return {"answer_correctness": float(not result["abstained"] and coverage == 1 and precision == 1),
            "answer_token_f1": f1, "fact_coverage": coverage, "citation_precision": precision}


def percentiles(values):
    return {"p50": float(np.percentile(values, 50)), "p95": float(np.percentile(values, 95))} if values else None


def _offline_vectors(texts, queries):
    # Explicit lexical test vectors, NOT a replacement for semantic embeddings.
    vocabulary = sorted(set(term for text in texts for term in terms(text)))
    def vectorize(text):
        tf = Counter(terms(text))
        return [float(tf[t]) for t in vocabulary]
    return [vectorize(t) for t in texts], {q["id"]: vectorize(q["question"]) for q in queries}


def evaluate(data, *, offline=False, k=5, strategies=STRATEGIES, qualities=("balanced",),
             answers=False, extraction=False, repeats=1):
    if offline and (answers or extraction):
        raise ValueError("Offline mode measures retrieval only; answers/extraction need real inference")
    chunks, metadata = [], []
    for doc in data["documents"]:
        for i, text in enumerate(embeddings.chunk_text(doc["text"])):
            chunks.append(text)
            metadata.append((doc, i))
    started = time.perf_counter()
    with llm.measure_usage() as setup_usage:
        if offline:
            vectors, query_vectors = _offline_vectors(chunks, data["queries"])
        else:
            vectors, query_vectors = llm.embed(chunks), {}
    corpus = Corpus([Candidate(i + 1, d["id"], pos, text, d["filename"], d.get("category"), v)
                     for i, (text, v, (d, pos)) in enumerate(zip(chunks, vectors, metadata))])
    report = {"mode": "offline_lexical_smoke" if offline else "live_provider",
              "created_at": datetime.now(timezone.utc).isoformat(), "k": k,
              "setup": {"latency_ms": (time.perf_counter() - started) * 1000, "usage": setup_usage.to_dict()},
              "config": {"chat_model": settings.openai_chat_model, "answer_model": settings.answer_model,
                         "complex_model": settings.complex_model, "embedding_model": settings.openai_embedding_model,
                         "reranker": "lexical" if offline else settings.reranker,
                         "context_tokens": settings.rag_context_tokens, "input_tokens": settings.llm_input_tokens,
                         "output_tokens": settings.llm_output_tokens, "chunk_tokens": settings.chunk_tokens,
                         "overlap_tokens": settings.chunk_overlap_tokens, "cache_ttl": settings.cache_ttl_seconds,
                         "model_prices": settings.model_prices, "repeats": repeats}, "comparisons": []}
    for quality in qualities:
        for strategy in strategies:
            rows = []
            for repeat in range(repeats):
                for q in data["queries"]:
                    start = time.perf_counter()
                    row = {"query_id": q["id"], "repeat": repeat, "error": None}
                    with llm.measure_usage(quality) as usage:
                        try:
                            query_vector = query_vectors.get(q["id"])
                            # Zero lexical fixture vectors are intentionally no-match.
                            if offline and not any(query_vector):
                                query_vector = [1e-30] * len(corpus.entries[0].vector)
                            hits = retrieve(q["question"], corpus, strategy, k, query_vector,
                                            "lexical" if offline else None)
                            row["retrieval_latency_ms"] = (time.perf_counter() - start) * 1000
                            row["document_ids"] = [c.document_id for c in hits]
                            row.update(retrieval_metrics(row["document_ids"], q["relevant_document_ids"], k))
                            if answers:
                                # Reuse the already measured ranking; avoid double retrieval/rerank.
                                result = generate_answer(q["question"], hits)
                                row.update(answer_metrics(result, q))
                                row["answer"] = result
                        except Exception as error:
                            row.update({"error": type(error).__name__, "recall_at_k": 0 if q["relevant_document_ids"] else None,
                                        "mrr": 0 if q["relevant_document_ids"] else None})
                            if answers:
                                row["answer_correctness"] = 0.0
                    row["latency_ms"] = (time.perf_counter() - start) * 1000
                    row["usage"] = usage.to_dict()
                    rows.append(row)
            metrics = {}
            for metric in ("recall_at_k", "mrr", "answer_correctness", "answer_token_f1", "fact_coverage", "citation_precision"):
                values = [r[metric] for r in rows if r.get(metric) is not None]
                metrics[metric] = sum(values) / len(values) if values else None
            costs = [r["usage"]["estimated_cost_usd"] for r in rows]
            report["comparisons"].append({"strategy": strategy, "quality": quality, **metrics,
                "latency_ms": percentiles([r["latency_ms"] for r in rows]),
                "retrieval_latency_ms": percentiles([r["retrieval_latency_ms"] for r in rows if "retrieval_latency_ms" in r]),
                "errors": sum(r["error"] is not None for r in rows),
                "tokens": sum(r["usage"]["input_tokens"] + r["usage"]["output_tokens"] for r in rows),
                "estimated_cost_usd": sum(costs) if all(c is not None for c in costs) else None,
                "results": rows})
    if extraction:
        matched = total = correct = 0
        rows = []
        for doc in data["documents"]:
            start = time.perf_counter()
            expected = doc.get("expected_fields", {})
            with llm.measure_usage() as usage:
                try:
                    cls = classifier.classify(doc["text"])
                    fields = extractor.extract_fields(doc["text"], cls["category"])
                    score = score_fields(expected, fields)
                    matched += score.matched
                    correct += cls["category"] == doc["category"]
                    row = {"document_id": doc["id"], "field_accuracy": score.accuracy, "error": None}
                except Exception as error:
                    row = {"document_id": doc["id"], "field_accuracy": 0, "error": type(error).__name__}
                total += len(expected)
            rows.append({**row, "latency_ms": (time.perf_counter() - start) * 1000, "usage": usage.to_dict()})
        report["extraction"] = {"field_accuracy": matched / total if total else None,
                                "classification_accuracy": correct / len(data["documents"]), "results": rows}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--answers", action="store_true")
    parser.add_argument("--extraction", action="store_true")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--strategies", nargs="+", choices=STRATEGIES, default=list(STRATEGIES))
    parser.add_argument("--qualities", nargs="+", choices=("balanced", "high"), default=["balanced"])
    parser.add_argument("--cache", choices=("cold", "warm"), default="cold")
    parser.add_argument("--context-tokens", type=int)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--min-recall", type=float)
    parser.add_argument("--min-answer-correctness", type=float)
    args = parser.parse_args()
    if args.k < 1 or args.repeats < 1:
        parser.error("k and repeats must be positive")
    if args.offline and (args.answers or args.extraction):
        parser.error("--offline cannot measure generated answers or extracted fields")
    if args.min_answer_correctness is not None and not args.answers:
        parser.error("--min-answer-correctness requires --answers")
    if args.context_tokens:
        if args.context_tokens < 256 or args.context_tokens + 2000 > settings.llm_input_tokens:
            parser.error("context-tokens must reserve 2000 tokens within LLM_INPUT_TOKENS")
        settings.rag_context_tokens = args.context_tokens
    if args.cache == "cold":
        settings.cache_ttl_seconds = 0
    data = load_dataset(args.dataset)
    try:
        report = evaluate(data, offline=args.offline, k=args.k, strategies=args.strategies, qualities=args.qualities,
                          answers=args.answers, extraction=args.extraction, repeats=args.repeats)
    except Exception as error:
        print(json.dumps({"error": type(error).__name__, "stage": "setup",
                          "message": "Evaluation could not start; check provider credentials, quota and Redis connectivity"}))
        return 2
    report["dataset_sha256"] = hashlib.sha256(args.dataset.read_bytes()).hexdigest()
    output = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n")
    print(json.dumps({**{key: value for key, value in report.items() if key != "comparisons"},
                      "comparisons": [{k: v for k, v in c.items() if k != "results"} for c in report["comparisons"]]}, indent=2))
    failed = any(c["errors"] for c in report["comparisons"])
    if args.extraction:
        failed |= any(r["error"] for r in report["extraction"]["results"])
    for metric, threshold in (("recall_at_k", args.min_recall), ("answer_correctness", args.min_answer_correctness)):
        if threshold is not None:
            failed |= any(c[metric] is None or c[metric] < threshold for c in report["comparisons"])
    return int(bool(failed))


if __name__ == "__main__":
    raise SystemExit(main())
