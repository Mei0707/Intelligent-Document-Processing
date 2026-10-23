import unittest
from unittest.mock import patch
from app.services import embeddings, tokens
from app.services.retrieval import Candidate, Corpus, fuse, retrieve, rerank
from app.services.rag import generate_answer
from evals.rag import answer_metrics, retrieval_metrics, load_dataset, evaluate, DEFAULT_DATASET


def candidate(cid, did, text, vector):
    return Candidate(cid, did, 0, text, f"doc-{did}.txt", None, vector)


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.corpus = Corpus([
            candidate(1, 1, "Invoice INV-42 from Acme total 12000 USD due March 2.", [1., 0.]),
            candidate(2, 2, "Contract with Globex renews in April.", [0., 1.]),
            candidate(3, 1, "Payment on INV-42 must be made by March 2.", [.9, .1]),
        ])

    def test_chunking_is_bounded_unicode_source_preserving_and_finite(self):
        text = ("日本語の文書. Important invoice amount 12000.\n\n" * 80).strip()
        chunks = embeddings.chunk_text(text, 48, 8)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(c in text and tokens.count(c) <= 48 for c in chunks))
        self.assertTrue(text.startswith(chunks[0]))
        self.assertTrue(text.endswith(chunks[-1]))
        for size, overlap in ((0, 0), (10, 10), (10, -1)):
            with self.assertRaises(ValueError):
                embeddings.chunk_text(text, size, overlap)

    def test_bm25_exact_identifier_and_no_provider_required(self):
        with patch("app.services.llm.embed", side_effect=AssertionError("No embeddings for BM25")):
            hits = retrieve("INV-42", self.corpus, "bm25", 2)
        self.assertEqual({h.document_id for h in hits}, {1})
        self.assertEqual(retrieve("unmatchedxyz", self.corpus, "bm25"), [])

    def test_vector_and_hybrid_keep_multiple_passages(self):
        hits = retrieve("invoice", self.corpus, "vector", 3, [1, 0])
        self.assertEqual([h.chunk_id for h in hits], [1, 3])
        fused = fuse(self.corpus.bm25("Globex"), self.corpus.vector_search([1, 0]), limit=10)
        self.assertEqual(len({c.chunk_id for c in fused}), len(fused))
        self.assertEqual({c.document_id for c in fused}, {1, 2})
        with self.assertRaises(ValueError):
            self.corpus.vector_search([1, 0, 0])

    def test_llm_reranker_changes_order_and_rejects_unknown_ids(self):
        hits = self.corpus.entries[:2]
        with patch("app.services.llm.chat_json", return_value={"scores": {"1": .1, "2": .9}}):
            self.assertEqual(rerank("Globex", hits, "llm")[0].chunk_id, 2)
        with patch("app.services.llm.chat_json", return_value={"scores": {"999": 1}}):
            with self.assertRaises(ValueError):
                rerank("Globex", hits, "llm")

    def test_answer_validates_sources_and_quote_and_server_builds_markers(self):
        with patch("app.services.llm.chat_json", return_value={"claims": [
            {"text": "The total is 12000 USD. [999]", "sources": [{"chunk_id": 1, "quote": "total 12000 USD"}]},
            {"text": "Fabricated claim", "sources": [{"chunk_id": 1, "quote": "a made up quote"}]},
            {"text": "Unknown document", "sources": [{"chunk_id": 999, "quote": "total 12000 USD"}]},
        ]}):
            result = generate_answer("Total?", self.corpus.entries)
        self.assertFalse(result["abstained"])
        self.assertEqual(len(result["citations"]), 1)
        self.assertIn("[1]", result["answer"])
        self.assertNotIn("999", result["answer"])
        self.assertNotIn("Fabricated", result["answer"])
        self.assertIn("digest=", result["citations"][0]["url"])
        with patch("app.services.llm.chat_json", return_value={"claims": []}):
            self.assertTrue(generate_answer("Unknown?", self.corpus.entries)["abstained"])
        with patch("app.services.llm.chat_json", side_effect=AssertionError("No evidence must skip LLM")):
            self.assertTrue(generate_answer("Unknown?", [])["abstained"])


class EvaluationTests(unittest.TestCase):
    def test_recall_and_mrr_handle_duplicates_and_unanswerable(self):
        self.assertEqual(retrieval_metrics([1, 1, 2], [1, 2], 2), {"recall_at_k": .5, "mrr": 1.})
        self.assertEqual(retrieval_metrics([3, 2, 1], [1, 2], 3), {"recall_at_k": 1., "mrr": .5})
        self.assertIsNone(retrieval_metrics([1], [], 1)["recall_at_k"])

    def test_fact_scoring_and_abstention(self):
        q = {"required_facts": [["no", "not"], ["under review"]], "reference_answer": "No. Under review.", "relevant_document_ids": [1]}
        result = {"answer": "No. Under review. [1]", "abstained": False, "citations": [{"document_id": 1}]}
        self.assertEqual(answer_metrics(result, q)["answer_correctness"], 1)
        result["answer"] = "Northwind is under review."
        self.assertEqual(answer_metrics(result, q)["answer_correctness"], 0)  # 'no' must be a whole word
        self.assertEqual(answer_metrics({"abstained": True}, {"unanswerable": True})["answer_correctness"], 1)

    def test_labeled_offline_comparison_runs_all_strategies(self):
        data = load_dataset(DEFAULT_DATASET)
        with patch("app.services.llm.embed", side_effect=AssertionError("Offline must never call API")):
            report = evaluate(data, offline=True, k=3)
        self.assertEqual(len(report["comparisons"]), 4)
        self.assertTrue(all(c["errors"] == 0 for c in report["comparisons"]))
        self.assertTrue(all(c["answer_correctness"] is None for c in report["comparisons"]))


if __name__ == "__main__":
    unittest.main()
