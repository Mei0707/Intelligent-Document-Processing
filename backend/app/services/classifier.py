from . import llm

CATEGORIES = [
    "Invoice",
    "Contract",
    "Resume",
    "Financial Report",
    "Insurance Claim",
    "Other",
]

_SYSTEM = (
    "You are a document classifier. Given the text of a business document, "
    "decide which single category it best fits. Categories: "
    + ", ".join(CATEGORIES)
    + ". Be strict: if it does not clearly fit one of the named categories, "
    "use 'Other'."
)

_SCHEMA = '{"category": "<one of the categories>", "confidence": <float 0-1>, "reason": "<short>"}'


def classify(text: str) -> dict:
    snippet = text[:4000] if text else ""
    if not snippet.strip():
        return {"category": "Other", "confidence": 0.0, "reason": "empty document"}

    result = llm.chat_json(_SYSTEM, snippet, schema_hint=_SCHEMA)
    category = result.get("category", "Other")
    if category not in CATEGORIES:
        category = "Other"
    try:
        confidence = float(result.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "category": category,
        "confidence": max(0.0, min(1.0, confidence)),
        "reason": result.get("reason", ""),
    }
