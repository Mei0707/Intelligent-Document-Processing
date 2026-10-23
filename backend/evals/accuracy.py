"""Run a labeled accuracy evaluation against the current AI pipeline.

This intentionally exercises the real classifier and extractor services, so
it requires OPENAI_API_KEY unless callers inject fake functions in tests.
"""

from __future__ import annotations

import argparse
import importlib
import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

DEFAULT_DATASET = Path(__file__).with_name("accuracy_dataset.json")


ClassifierFn = Callable[[str], dict[str, Any]]
ExtractorFn = Callable[[str, str], dict[str, Any]]


@dataclass(frozen=True)
class FieldScore:
    matched: int
    total: int

    @property
    def accuracy(self) -> float:
        return self.matched / self.total if self.total else 0.0


def _normalize_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = " ".join(value.strip().lower().split())
        normalized = re.sub(r"[$,]", "", normalized)
        if re.fullmatch(r"-?\d+(\.\d+)?", normalized):
            return round(float(normalized), 2)
        return normalized
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return None
        return round(float(value), 2)
    return value


def normalize_value(value: Any) -> Any:
    """Normalize extracted values so harmless formatting differences do not fail."""
    if isinstance(value, list):
        normalized = [normalize_value(item) for item in value]
        return sorted(normalized, key=lambda item: json.dumps(item, sort_keys=True))
    if isinstance(value, dict):
        return {str(k): normalize_value(v) for k, v in sorted(value.items())}
    return _normalize_scalar(value)


def values_match(expected: Any, actual: Any) -> bool:
    return normalize_value(expected) == normalize_value(actual)


def score_fields(expected: dict[str, Any], actual: dict[str, Any]) -> FieldScore:
    matched = 0
    for key, expected_value in expected.items():
        if values_match(expected_value, actual.get(key)):
            matched += 1
    return FieldScore(matched=matched, total=len(expected))


def load_dataset(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("Dataset must be a JSON list of examples.")
    for i, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Example {i} must be an object.")
        for required in ("id", "text", "expected_category"):
            if required not in item:
                raise ValueError(f"Example {i} is missing '{required}'.")
        item.setdefault("expected_fields", {})
    return data


def evaluate(
    examples: list[dict[str, Any]],
    classify_fn: ClassifierFn | None = None,
    extract_fn: ExtractorFn | None = None,
    include_extraction: bool = True,
) -> dict[str, Any]:
    if classify_fn is None or extract_fn is None:
        try:
            classifier = importlib.import_module("app.services.classifier")
            extractor = importlib.import_module("app.services.extractor")
        except ModuleNotFoundError as exc:
            if exc.name != "app":
                raise
            classifier = importlib.import_module("backend.app.services.classifier")
            extractor = importlib.import_module("backend.app.services.extractor")

        classify_fn = classify_fn or classifier.classify
        extract_fn = extract_fn or extractor.extract_fields

    results: list[dict[str, Any]] = []
    category_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"correct": 0, "total": 0})
    classification_correct = 0
    field_matched = 0
    field_total = 0

    for example in examples:
        text = example["text"]
        expected_category = example["expected_category"]
        prediction = classify_fn(text)
        predicted_category = prediction.get("category")
        is_correct_category = predicted_category == expected_category
        classification_correct += int(is_correct_category)
        category_stats[expected_category]["correct"] += int(is_correct_category)
        category_stats[expected_category]["total"] += 1

        result: dict[str, Any] = {
            "id": example["id"],
            "expected_category": expected_category,
            "predicted_category": predicted_category,
            "category_confidence": prediction.get("confidence"),
            "classification_correct": is_correct_category,
        }

        expected_fields = example.get("expected_fields") or {}
        if include_extraction and expected_fields:
            extracted = extract_fn(text, predicted_category or expected_category)
            field_score = score_fields(expected_fields, extracted)
            field_matched += field_score.matched
            field_total += field_score.total
            result.update(
                {
                    "expected_fields": expected_fields,
                    "extracted_fields": extracted,
                    "field_matched": field_score.matched,
                    "field_total": field_score.total,
                    "field_accuracy": round(field_score.accuracy, 4),
                }
            )

        results.append(result)

    total = len(examples)
    return {
        "total_examples": total,
        "classification": {
            "correct": classification_correct,
            "total": total,
            "accuracy": round(classification_correct / total, 4) if total else 0.0,
            "by_expected_category": {
                category: {
                    "correct": stats["correct"],
                    "total": stats["total"],
                    "accuracy": round(stats["correct"] / stats["total"], 4)
                    if stats["total"]
                    else 0.0,
                }
                for category, stats in sorted(category_stats.items())
            },
        },
        "field_extraction": {
            "matched": field_matched,
            "total": field_total,
            "accuracy": round(field_matched / field_total, 4) if field_total else None,
        },
        "results": results,
    }


def print_report(report: dict[str, Any]) -> None:
    classification = report["classification"]
    fields = report["field_extraction"]

    print("Accuracy evaluation")
    print("===================")
    print(f"Examples: {report['total_examples']}")
    print(
        "Classification: "
        f"{classification['correct']}/{classification['total']} "
        f"({classification['accuracy']:.2%})"
    )
    if fields["total"]:
        print(
            "Field extraction: "
            f"{fields['matched']}/{fields['total']} "
            f"({fields['accuracy']:.2%})"
        )
    else:
        print("Field extraction: no expected fields scored")

    print("\nBy expected category:")
    for category, stats in classification["by_expected_category"].items():
        print(f"- {category}: {stats['correct']}/{stats['total']} ({stats['accuracy']:.2%})")

    incorrect = [r for r in report["results"] if not r["classification_correct"]]
    if incorrect:
        print("\nClassification misses:")
        for item in incorrect:
            print(
                f"- {item['id']}: expected {item['expected_category']}, "
                f"predicted {item['predicted_category']}"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure classifier/extractor accuracy.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--json", action="store_true", help="Print the full JSON report.")
    parser.add_argument(
        "--skip-extraction",
        action="store_true",
        help="Only score document classification.",
    )
    parser.add_argument(
        "--min-classification-accuracy",
        type=float,
        default=None,
        help="Exit non-zero if classification accuracy is below this decimal threshold.",
    )
    parser.add_argument(
        "--min-field-accuracy",
        type=float,
        default=None,
        help="Exit non-zero if field extraction accuracy is below this decimal threshold.",
    )
    args = parser.parse_args()

    examples = load_dataset(args.dataset)
    if args.limit is not None:
        examples = examples[: args.limit]

    try:
        report = evaluate(examples, include_extraction=not args.skip_extraction)
    except ModuleNotFoundError as exc:
        missing = exc.name or "a required package"
        print(f"Missing Python dependency: {missing}")
        print("Install backend dependencies, then rerun the evaluator:")
        print("  cd backend")
        print("  python3 -m pip install -r requirements.txt")
        return 2
    except RuntimeError as exc:
        if "OPENAI_API_KEY" not in str(exc):
            raise
        print("OPENAI_API_KEY is not configured.")
        print("Create backend/.env from backend/.env.example and add your key, or export it in your shell.")
        return 2
    except Exception as exc:
        module = exc.__class__.__module__
        if module.startswith("openai"):
            print(f"OpenAI API request failed: {exc}")
            print("Check your network connection, API key validity, model access, and account billing.")
            return 2
        raise

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print_report(report)

    failed = False
    classification_accuracy = report["classification"]["accuracy"]
    if (
        args.min_classification_accuracy is not None
        and classification_accuracy < args.min_classification_accuracy
    ):
        failed = True
        print(
            "\nFAIL: classification accuracy "
            f"{classification_accuracy:.2%} is below "
            f"{args.min_classification_accuracy:.2%}"
        )

    field_accuracy = report["field_extraction"]["accuracy"]
    if (
        args.min_field_accuracy is not None
        and field_accuracy is not None
        and field_accuracy < args.min_field_accuracy
    ):
        failed = True
        print(
            "\nFAIL: field extraction accuracy "
            f"{field_accuracy:.2%} is below {args.min_field_accuracy:.2%}"
        )

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
