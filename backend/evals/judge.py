"""LLM-as-judge for the full evaluation mode: answer correctness against a reference, and whether every
claim is supported by the evidence the agent had. Deterministic checks run in every mode; the judge
adds what string matching cannot see (paraphrases, wrong-but-plausible statements)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.llm.client import LLMClient, LLMUnavailable


class Verdict(BaseModel):
    correctness: int = Field(description="1 = wrong, 3 = partly right, 5 = fully right and complete")
    faithful: bool = Field(description="True if every factual claim is supported by the EVIDENCE or is a refusal")
    reason: str = Field(description="One short sentence")


JUDGE_PROMPT = """You grade a customer-support assistant. Be strict and concise.
- correctness (1-5): does the ANSWER give the information in the REFERENCE (same facts, any wording or
  language)? An honest "I don't know" scores 5 when the reference says the information is not available.
- faithful: false if the ANSWER states any fact (price, date, stock, status, policy, delay) that is not in
  the EVIDENCE. Greetings, refusals and offers to contact a human are faithful.
Reply with JSON only."""


async def judge(llm: LLMClient, case: dict[str, Any], answer: str, evidence: str) -> dict[str, Any] | None:
    messages = [
        {"role": "system", "content": JUDGE_PROMPT},
        {
            "role": "user",
            "content": f"QUESTION: {case['question']}\nREFERENCE: {case['expect'].get('reference', '')}\n"
            f"EVIDENCE:\n{evidence[:6000] or '(none)'}\n\nANSWER: {answer}",
        },
    ]
    try:
        verdict, usages = await llm.structured(
            messages=messages, schema=Verdict, tier="smart", purpose="judge", max_tokens=200
        )
    except LLMUnavailable:
        return None
    return {
        **verdict.model_dump(),
        "correctness": max(1, min(5, verdict.correctness)),
        "model": usages[-1].model,
        "cost_usd": sum(u.cost_usd for u in usages),
    }
