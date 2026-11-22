"""Removal of personal and secret data before anything is logged or traced."""

from __future__ import annotations

import re
from typing import Any

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[email]"),
    (re.compile(r"\b(?:eyJ[A-Za-z0-9_-]{8,}\.){2}[A-Za-z0-9_-]{8,}\b"), "[jwt]"),
    (re.compile(r"\b(?:sk|pk|lf|gho|ghp)[-_][A-Za-z0-9_-]{12,}\b"), "[secret]"),
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "[card]"),
    (re.compile(r"(?<!\w)\+?\d[\d ()-]{7,}\d(?!\w)"), "[phone]"),
]

SENSITIVE_KEYS = {
    "password",
    "password_hash",
    "token",
    "access_token",
    "authorization",
    "api_key",
    "secret",
    "customer_token",
    "email",
    "phone",
    "address",
    "shipping_address",
}


def redact_text(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def redact(value: Any, depth: int = 0) -> Any:
    """Recursively redact strings and sensitive keys in dicts/lists."""
    if depth > 6:
        return "[truncated]"
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {
            k: ("[redacted]" if str(k).lower() in SENSITIVE_KEYS else redact(v, depth + 1)) for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [redact(v, depth + 1) for v in value]
    return value
