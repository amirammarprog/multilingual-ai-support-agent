"""Complexity router: send easy turns to the cheap model and hard ones to the capable model.

The score is a transparent sum of features so every decision can be explained in the dashboard and
tuned with the evaluation suite (run the evals with ROUTER_MODE=always_fast / always_smart / auto and
compare quality against cost).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.config import Settings, get_settings
from app.llm.client import Tier

_MULTI_INTENT = re.compile(
    r"\b(and also|also|as well as|et aussi|aussi|en plus|ainsi que)\b|(وكذلك|وأيضا|و زادة|وزادة)",
    re.IGNORECASE,
)
_UPSET = re.compile(
    r"\b(angry|unacceptable|scam|lawyer|complain|furious|worst|disappointed|inadmissible|arnaque|avocat|"
    r"plainte|scandale|déçu|decu|furieux)\b|(غاضب|مستاء|احتيال|شكوى|محامي|فضيحة|مقلق|معقول|ماعجبنيش)",
    re.IGNORECASE,
)
_FOLLOW_UP = re.compile(
    r"\b(it|this|that|they|them|one|ones|same|ça|celui|celle|ceux|le même|la même)\b|(هذا|هذه|هاذا|هاذي|نفسه|هو|هي)",
    re.IGNORECASE,
)


@dataclass
class RouteDecision:
    tier: Tier
    score: float
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {"tier": self.tier, "score": round(self.score, 2), "reasons": self.reasons}


def route(
    message: str,
    *,
    language: str,
    dialect: str | None,
    history_turns: int,
    guard_action: str,
    settings: Settings | None = None,
) -> RouteDecision:
    settings = settings or get_settings()
    if settings.router_mode == "always_fast":
        return RouteDecision("fast", 0.0, ["forced: always_fast"])
    if settings.router_mode == "always_smart":
        return RouteDecision("smart", 1.0, ["forced: always_smart"])

    score, reasons = 0.0, []

    def add(points: float, reason: str) -> None:
        nonlocal score
        score += points
        reasons.append(f"+{points:g} {reason}")

    words = len(message.split())
    if words > 30:
        add(0.25, "long message")
    if message.count("?") + message.count("؟") >= 2 or _MULTI_INTENT.search(message):
        add(0.3, "several questions")
    if dialect == "tn":
        add(0.5, "Tunisian Arabic")
    elif language == "ar":
        add(0.15, "Arabic")
    if history_turns >= 2 and words <= 12 and _FOLLOW_UP.search(message):
        add(0.25, "follow-up that depends on context")
    if guard_action == "flag":
        add(0.5, "suspicious request")
    if _UPSET.search(message):
        add(0.3, "upset customer")
    tier: Tier = "smart" if score >= settings.router_smart_threshold else "fast"
    return RouteDecision(tier, score, reasons or ["simple request"])
