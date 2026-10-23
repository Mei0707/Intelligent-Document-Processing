import unittest

from evals.accuracy import evaluate, score_fields, values_match


class AccuracyEvalTests(unittest.TestCase):
    def test_values_match_normalizes_common_formatting(self):
        self.assertTrue(values_match("$4,700.00", 4700))
        self.assertTrue(values_match(" Acme   Supplies ", "acme supplies"))
        self.assertTrue(values_match(["Python", "AWS"], ["aws", " python "]))

    def test_score_fields_counts_expected_keys_only(self):
        score = score_fields(
            {"invoice_number": "INV-1007", "total_amount": 4700},
            {"invoice_number": "inv-1007", "total_amount": "$4,700.00", "extra": "ignored"},
        )

        self.assertEqual(score.matched, 2)
        self.assertEqual(score.total, 2)
        self.assertEqual(score.accuracy, 1.0)

    def test_evaluate_reports_classification_and_field_accuracy(self):
        examples = [
            {
                "id": "a",
                "text": "invoice text",
                "expected_category": "Invoice",
                "expected_fields": {"invoice_number": "INV-1"},
            },
            {
                "id": "b",
                "text": "contract text",
                "expected_category": "Contract",
                "expected_fields": {"governing_law": "New York"},
            },
        ]

        def fake_classify(text):
            return {
                "invoice text": {"category": "Invoice", "confidence": 0.9},
                "contract text": {"category": "Invoice", "confidence": 0.4},
            }[text]

        def fake_extract(text, category):
            return {
                "invoice text": {"invoice_number": "INV-1"},
                "contract text": {"governing_law": None},
            }[text]

        report = evaluate(examples, classify_fn=fake_classify, extract_fn=fake_extract)

        self.assertEqual(report["classification"]["correct"], 1)
        self.assertEqual(report["classification"]["total"], 2)
        self.assertEqual(report["classification"]["accuracy"], 0.5)
        self.assertEqual(report["field_extraction"]["matched"], 1)
        self.assertEqual(report["field_extraction"]["total"], 2)
        self.assertEqual(report["field_extraction"]["accuracy"], 0.5)


if __name__ == "__main__":
    unittest.main()
