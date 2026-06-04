from . import llm

_PROMPTS = {
    "Invoice": "Summarize this invoice in 2-3 sentences: who is billing whom, for how much, and when payment is due.",
    "Contract": "Summarize this contract: identify the parties, the purpose, and the most important obligations or risks in 3-4 sentences.",
    "Resume": "Summarize this resume as a 2-3 sentence candidate profile covering seniority, core skills, and notable experience.",
    "Financial Report": "Summarize this financial report: company, period, headline metrics, and 1-2 highlights or concerns in 3-4 sentences.",
    "Insurance Claim": "Summarize this insurance claim: claimant, incident, amount sought, and current status in 2-3 sentences.",
    "Other": "Write a concise 2-3 sentence executive summary of this document.",
}


def summarize(text: str, category: str) -> str:
    if not text or not text.strip():
        return ""
    prompt = _PROMPTS.get(category, _PROMPTS["Other"])
    snippet = text[:8000]
    return llm.chat_text(
        system="You write factual, neutral document summaries. Do not invent details.",
        user=f"{prompt}\n\n---\n{snippet}",
        max_tokens=250,
    )
