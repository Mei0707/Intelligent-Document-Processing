"""Category-aware structured field extraction."""

from . import llm

_FIELDS_BY_CATEGORY = {
    "Invoice": {
        "fields": ["invoice_number", "vendor", "bill_to", "issue_date", "due_date", "total_amount", "currency", "line_items"],
        "hint": '{"invoice_number": "...", "vendor": "...", "bill_to": "...", "issue_date": "YYYY-MM-DD", "due_date": "YYYY-MM-DD", "total_amount": <number>, "currency": "USD", "line_items": [{"description": "...", "amount": <number>}]}',
    },
    "Contract": {
        "fields": ["parties", "effective_date", "expiration_date", "renewal_terms", "governing_law", "key_obligations"],
        "hint": '{"parties": ["..."], "effective_date": "YYYY-MM-DD", "expiration_date": "YYYY-MM-DD", "renewal_terms": "...", "governing_law": "...", "key_obligations": ["..."]}',
    },
    "Resume": {
        "fields": ["name", "email", "phone", "skills", "education", "experience", "years_experience"],
        "hint": '{"name": "...", "email": "...", "phone": "...", "skills": ["..."], "education": [{"degree": "...", "school": "...", "year": "..."}], "experience": [{"title": "...", "company": "...", "duration": "..."}], "years_experience": <number>}',
    },
    "Financial Report": {
        "fields": ["company", "period", "revenue", "net_income", "currency", "highlights"],
        "hint": '{"company": "...", "period": "...", "revenue": <number>, "net_income": <number>, "currency": "USD", "highlights": ["..."]}',
    },
    "Insurance Claim": {
        "fields": ["claim_number", "claimant", "policy_number", "incident_date", "claim_amount", "status", "description"],
        "hint": '{"claim_number": "...", "claimant": "...", "policy_number": "...", "incident_date": "YYYY-MM-DD", "claim_amount": <number>, "status": "...", "description": "..."}',
    },
    "Other": {
        "fields": ["title", "author", "date", "topics", "key_points"],
        "hint": '{"title": "...", "author": "...", "date": "YYYY-MM-DD", "topics": ["..."], "key_points": ["..."]}',
    },
}


def extract_fields(text: str, category: str) -> dict:
    spec = _FIELDS_BY_CATEGORY.get(category, _FIELDS_BY_CATEGORY["Other"])
    snippet = text[:8000] if text else ""
    if not snippet.strip():
        return {}

    system = (
        f"Extract the following fields from a {category} document: "
        f"{', '.join(spec['fields'])}. "
        "Use null for fields that are not present. Do not hallucinate values. "
        "Dates must be ISO 8601 (YYYY-MM-DD) when possible. "
        "Numeric amounts must be numbers, not strings."
    )
    return llm.chat_json(system, snippet, schema_hint=spec["hint"])
