"""Input and output guardrails.

These checks are deterministic on purpose: they cost nothing, cannot be talked out of their job,
and their decisions are easy to test. They are one layer only. The decisive protections are that
tools authorise every call server side, prices are read-only, and answers are checked against the
evidence they were built from.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Literal

# --------------------------------------------------------------------------- normalisation ----
_INVISIBLE = re.compile("[​-‏‪-‮⁠-⁤⁦-⁩﻿­]")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SPACES = re.compile(r"[ \t]{2,}")
# Arabic tatweel and diacritics do not change meaning but can be used to dodge patterns.
_ARABIC_DECOR = re.compile("[ـً-ٰٟ]")


def normalize_input(text: str, max_chars: int = 2000) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = _INVISIBLE.sub("", text)
    text = _CONTROL.sub(" ", text)
    text = _SPACES.sub(" ", text).strip()
    return text[:max_chars]


def _for_matching(text: str) -> str:
    text = _ARABIC_DECOR.sub("", normalize_input(text, 10_000)).lower()
    # Undo common leetspeak used to hide keywords ("1gn0re", "pr0mpt").
    return text.translate(str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "@": "a", "$": "s"}))


# --------------------------------------------------------------------------- injection rules ----
@dataclass(frozen=True)
class Rule:
    category: str
    weight: float
    pattern: re.Pattern[str]


def _r(category: str, weight: float, *patterns: str) -> list[Rule]:
    return [Rule(category, weight, re.compile(p, re.IGNORECASE | re.UNICODE)) for p in patterns]


RULES: list[Rule] = [
    *_r(
        "instruction_override",
        0.7,
        r"\b(ignore|disregard|forget|override|bypass|skip)\b.{0,30}\b(previous|prior|above|earlier|all|any|your|the|system)?\s*"
        r"(instructions?|rules?|prompts?|guidelines?|directives?|policies|restrictions?)\b",
        r"\b(ignore|oublie|oubliez|ignorez|ignorer)\b.{0,30}\b(instructions?|consignes?|r[eè]gles?|directives?)\b",
        r"(تجاهل|انس|إنس|انسى|تخط|تجاوز)\S*\s+.{0,20}(التعليمات|الأوامر|القواعد|التوجيهات|تعليماتك)",
        r"\bnew (instructions?|rules?)\s*:",
        r"\bnouvelles? (instructions?|consignes?)\s*:",
    ),
    *_r(
        "prompt_extraction",
        0.7,
        r"\b(reveal|show|print|repeat|display|output|tell me|give me|leak|dump)\b.{0,30}\b(system|hidden|initial|original|your)\s*"
        r"(prompt|instructions?|message|rules|configuration)\b",
        r"\b(what are|what is) your (system )?(prompt|instructions?|rules)\b",
        r"\b(r[ée]v[eè]le|affiche|montre|r[ée]p[eè]te|donne)[sz]?\b.{0,30}\b(ton|tes|le|les|votre|vos)\s*(prompt|instructions?|consignes?)\b",
        r"(اكشف|اعرض|اطبع|كرر|أعطني|اعطني|ورّيني|وريني)\S*\s+.{0,20}(التعليمات|البرومبت|موجه النظام|الأوامر المخفية|تعليماتك)",
    ),
    *_r(
        "role_hijack",
        0.6,
        r"\byou are (now|no longer)\b",
        r"\b(act|behave|respond) as (an? )?(unrestricted|unfiltered|evil|jailbroken|dan|developer|admin|system)\b",
        r"\b(developer|god|admin|debug|maintenance|jailbreak) mode\b",
        r"\bdo anything now\b|\bjailbreak\b|\bDAN\b",
        r"\btu es (maintenant|désormais|desormais)\b|\bmode (développeur|developpeur|admin|debug)\b",
        r"(أنت الآن|انت الآن|من الآن أنت|وضع المطور|وضع المسؤول)",
        r"\bpretend (to be|you are)\b|\bfais comme si tu (étais|etais)\b",
    ),
    *_r(
        "special_tokens",
        0.8,
        r"<\|?(im_start|im_end|system|endoftext|eot_id|start_header_id)\|?>",
        r"^\s*(###|\[)\s*(system|assistant|developer)\s*(\]|:)",
        r"\bBEGIN (SYSTEM|ADMIN) (PROMPT|MESSAGE)\b",
        r"</?(system|instructions?)>",
    ),
    *_r(
        "sql_injection",
        0.6,
        r"('|\")\s*(or|and)\s+('?\d+'?\s*=\s*'?\d+|'[^']*'\s*=\s*')",
        r"\bunion\s+(all\s+)?select\b",
        r"\b(drop|truncate|alter)\s+table\b",
        r";\s*(delete|update|insert|drop)\b",
        r"\bselect\s+(\*|\w+(\s*,\s*\w+)+)\s+from\s+\w+",
        r"\bselect\b.{0,30}\bfrom\s+(users|orders|customers|products|messages|shops|pg_\w+|information_schema)\b",
        r"--\s*$|/\*.*\*/",
    ),
    *_r(
        "data_exfiltration",
        0.6,
        r"\b(all|every|other|another)\s+(customers?|users?|clients?)('s|s')?\b.{0,20}\b(orders?|data|emails?|addresses|phones?|details)\b",
        r"\b(orders?|data|e-?mails?|addresses|phones?)\b.{0,20}\b(of|for|from|belonging to)\s+(all|every|other|another)\s+(customers?|users?|clients?)\b",
        r"\b(list|dump|export|give me)\b.{0,15}\b(all )?(customers?|users?|clients?|orders)\b.{0,15}\b(database|table|list|emails?)\b",
        r"\b(tous les|toutes les|autres?)\s+(clients?|commandes|utilisateurs)\b.{0,25}\b(e-?mails?|adresses|données|commandes)\b",
        r"(كل|جميع|بقية)\s+(الزبائن|العملاء|الحرفاء|المستخدمين).{0,20}(طلبات|بيانات|عناوين|ايميلات|إيميلات)",
    ),
    *_r(
        "price_manipulation",
        0.35,
        r"\b(set|change|update|lower|reduce|make)\b.{0,20}\bprices?\b.{0,20}\b(to|at|=)\s*\d",
        r"\b(apply|give|add)\b.{0,15}(\d{2,3}\s?%|\bfree\b|100 ?percent).{0,15}\b(discount|off|coupon|refund)\b",
        r"\b(make|give) (it|this|them|my order) (for )?free\b",
        r"\b(mets|change|modifie|baisse)[sz]?\b.{0,20}\bprix\b.{0,20}\b(à|a|=)\s*\d",
        r"\b(applique|donne|ajoute)[sz]?\b.{0,20}\b(remise|réduction|reduction|promo)\b.{0,15}\d{2,3}\s?%",
        r"(اجعل|غير|بدل|نقص)\S*\s+.{0,15}(السعر|الثمن).{0,15}\d",
        r"(خصم|تخفيض|ريميز)\s*.{0,10}(100|٩٠|90|80|٨٠|١٠٠)\s*(%|٪|بالمائة|بالمية)",
    ),
    *_r(
        "authority_claim",
        0.3,
        r"\b(i am|i'm|this is)\s+(the |your |a )?(\w+ )?(admin|administrator|owner|manager|developer|staff|ceo|system)\b",
        r"\bje suis\s+(le |la |l')?(admin|administrateur|gérant|gerant|propriétaire|proprietaire|développeur|developpeur|directeur)\b",
        r"(أنا|انا)\s+(المدير|المسؤول|الأدمن|الادمن|صاحب المتجر|المطور)",
    ),
]

Action = Literal["allow", "flag", "block"]
BLOCK_THRESHOLD = 0.6
FLAG_THRESHOLD = 0.3


@dataclass
class InjectionVerdict:
    score: float
    action: Action
    categories: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {"score": round(self.score, 3), "action": self.action, "categories": self.categories}


def scan_input(text: str) -> InjectionVerdict:
    """Score a user message for prompt-injection and abuse patterns."""
    target = _for_matching(text)
    raw = normalize_input(text, 10_000).lower()
    hits: dict[str, float] = {}
    for rule in RULES:
        if rule.category in hits:
            continue
        if rule.pattern.search(target) or rule.pattern.search(raw):
            hits[rule.category] = rule.weight
    remaining = 1.0
    for weight in hits.values():
        remaining *= 1 - weight
    score = 1 - remaining
    action: Action = "block" if score >= BLOCK_THRESHOLD else "flag" if score >= FLAG_THRESHOLD else "allow"
    return InjectionVerdict(score=score, action=action, categories=sorted(hits))


def scan_untrusted_document_text(text: str) -> InjectionVerdict:
    """Indirect prompt injection check for knowledge-base chunks. Policy text is descriptive; a chunk
    that addresses the assistant ("ignore your instructions", "you are now") is quarantined."""
    verdict = scan_input(text)
    relevant = [
        c
        for c in verdict.categories
        if c in {"instruction_override", "prompt_extraction", "role_hijack", "special_tokens"}
    ]
    if relevant:
        return InjectionVerdict(score=verdict.score, action="block", categories=relevant)
    return InjectionVerdict(score=0.0, action="allow", categories=[])


# --------------------------------------------------------------------------- output checks ----
_NUMBER = re.compile(r"\d+(?:[.,\s]\d{3})*(?:[.,]\d+)?")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"\+?\d[\d ()-]{7,}\d")
_PROMISES = re.compile(
    r"(i have|i've|we have|we've)\s+(applied|refunded|changed|updated|cancelled|canceled|issued)\b"
    r"|\b(j'ai|nous avons)\s+(appliqué|rembours[ée]|modifi[ée]|annul[ée]|chang[ée])\b"
    r"|(قمت|قمنا|تم)\s+(بتطبيق|تطبيق|باسترجاع|بتغيير|تغيير|بإلغاء|إلغاء|استرجاع)",
    re.IGNORECASE,
)
_LEAK = re.compile(
    r"(system prompt|my instructions (are|say)|i was instructed to|voici mes instructions|mes consignes sont"
    r"|تعليماتي هي|BEGIN SYSTEM)",
    re.IGNORECASE,
)


def _fmt(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".") or "0"


def number_readings(raw: str) -> set[str]:
    """Every plausible value of a written number. Separators are ambiguous across the shop's languages:
    "7,000 TND" is seven dinars in French, "1,299" is one thousand two hundred ninety-nine in English,
    and TND prices are written with three decimals ("1299.000")."""
    compact = re.sub(r"\s", "", raw)
    readings: set[str] = set()
    decimal = compact.replace(",", ".")
    if decimal.count(".") <= 1:
        readings.add(_fmt(float(decimal)))
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", compact):
        readings.add(_fmt(float(re.sub(r"[.,]", "", compact))))
    return readings


def _raw_numbers(text: str) -> list[str]:
    return _NUMBER.findall(text.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")))


def _numbers(text: str, with_parts: bool = False) -> set[str]:
    """All readings of all numbers in ``text``. ``with_parts`` also adds every digit run (used for
    evidence, so "2026-11-24" supports "24 November 2026")."""
    out: set[str] = set()
    for raw in _raw_numbers(text):
        out |= number_readings(raw)
    if with_parts:
        digits = text.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
        out |= {str(int(part)) for part in re.findall(r"\d+", digits)}
    return out


def unsupported_numbers(answer: str, evidence: str) -> list[str]:
    """Numbers written in ``answer`` with no reading that appears in ``evidence``. Single digits are
    ignored: they are mostly list markers or counts copied from the question."""
    evidence_numbers = _numbers(evidence, with_parts=True)
    missing = []
    for raw in _raw_numbers(answer):
        readings = number_readings(raw)
        if readings & evidence_numbers or len(re.sub(r"\D", "", raw)) <= 1:
            continue
        missing.append(raw.strip())
    return sorted(set(missing))


@dataclass
class OutputCheck:
    ok: bool
    problems: list[str] = field(default_factory=list)
    unsupported_numbers: list[str] = field(default_factory=list)
    redacted_answer: str = ""


def check_output(
    answer: str,
    evidence: str,
    allowed_contacts: set[str],
    canary: str,
) -> OutputCheck:
    """Validate a drafted answer against the evidence it was generated from."""
    problems: list[str] = []
    if canary and canary.lower() in answer.lower():
        problems.append("system_prompt_leak")
    if _LEAK.search(answer):
        problems.append("instruction_disclosure")
    if _PROMISES.search(answer):
        problems.append("unauthorised_action_claim")

    unsupported = unsupported_numbers(answer, evidence)
    if unsupported:
        problems.append("unsupported_numbers")

    allowed = {c.lower() for c in allowed_contacts}
    redacted = answer
    for email in set(_EMAIL.findall(answer)):
        if email.lower() not in allowed:
            redacted = redacted.replace(email, "[email removed]")
            problems.append("foreign_contact_data")
    for phone in set(_PHONE.findall(answer)):
        if re.sub(r"\D", "", phone) not in {re.sub(r"\D", "", c) for c in allowed}:
            # Long digit runs that are not phone numbers (tracking codes) are already in evidence.
            if re.sub(r"\D", "", phone) not in re.sub(r"\D", "", evidence):
                redacted = redacted.replace(phone, "[number removed]")
                problems.append("foreign_contact_data")
    return OutputCheck(
        ok=not problems,
        problems=sorted(set(problems)),
        unsupported_numbers=unsupported,
        redacted_answer=redacted,
    )
