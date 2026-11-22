"""Rule-based planner used when no LLM provider is reachable (degraded mode), and as the "offline"
baseline in the evaluation suite. It only extracts what is literally in the message."""

from __future__ import annotations

import re
from typing import Any

from app.agent.prompts import Plan

ORDER_RE = re.compile(r"\b([A-Za-z]{2})[- ]?(\d{4,6})\b")
SKU_RE = re.compile(r"\b[A-Z]{3,4}-[A-Z0-9]{1,6}(?:-[A-Z0-9]{1,6})?\b")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

_HUMAN = re.compile(
    r"\b(human|real person|someone|agent|operator|representative|humain|conseiller|quelqu'un|une personne|"
    r"op[ée]rateur)\b|(إنسان|موظف|شخص حقيقي|حد من الفريق|واحد من الفريق|نحكي مع|نتكلم مع)|\b(7ad|wa7ed)\b",
    re.IGNORECASE,
)
_TICKET = re.compile(
    r"\b(ticket|complaint|claim|r[ée]clamation|plainte|broken|cass[ée]|defect|d[ée]faut|"
    r"panne)\b|(شكوى|تذكرة|تيكيت|مكسور|معطب|عطل)",
    re.IGNORECASE,
)
_STOCK = re.compile(
    r"\b(in stock|available|availability|disponible|en stock|stock|restock)\b|(متوفر|متاح|مخزون|"
    r"ستوك|فما)|\b(famma|fama)\b",
    re.IGNORECASE,
)
_PRICE = re.compile(
    r"\b(price|cost|how much|prix|co[uû]te|combien|spec|specs|battery|batterie|caract[ée]ristiques|"
    r"warranty of)\b|(سعر|ثمن|بقداش|قداش|سوم|مواصفات|بطارية)|\b(9adech|kadech|soum)\b",
    re.IGNORECASE,
)
_SEARCH = re.compile(
    r"\b(looking for|recommend|suggest|need a|want a|je cherche|recommand|conseill|besoin d'un)\b|"
    r"(أبحث عن|نلوج على|نحب نشري|انصحني)|\b(nlawej|n7eb nechri)\b",
    re.IGNORECASE,
)
_ORDER_WORDS = re.compile(
    r"\b(order|commande|parcel|colis|tracking|suivi|delivery|livraison)\b|(طلب|طلبية|كوموند|"
    r"الكوموند|الطرد|التوصيل)|\b(commanda)\b",
    re.IGNORECASE,
)
_GREETING = re.compile(
    r"^\s*(hi|hello|hey|bonjour|salut|bonsoir|salam|aslema|ahla|مرحبا|السلام عليكم|سلام|"
    r"عسلامة|أهلا|اهلا)[\s!.,]*$",
    re.IGNORECASE,
)
_PRICE_CHANGE = re.compile(
    r"\b(discount|remise|r[ée]duction|coupon|free|gratuit)\b|(تخفيض|خصم|ريميز|مجاني)", re.IGNORECASE
)
_YES = re.compile(
    r"^\s*(yes|yes please|ok|okay|sure|oui|d'accord|ouais|نعم|اي|إي|ايه|باهي|ey|ih|behi)\b", re.IGNORECASE
)


def find_order_number(text: str) -> str | None:
    match = ORDER_RE.search(text)
    return f"{match.group(1).upper()}-{match.group(2)}" if match else None


# Hyphenated words that look like SKUs ("EST-CE", "PEUT-ÊTRE") but are not.
_NOT_SKUS = {"EST-CE", "QU'EST-CE", "PEUT-ETRE", "VOUS-MEME", "E-MAIL", "T-SHIRT", "WI-FI"}


def find_sku(text: str) -> str | None:
    """A SKU-looking token; tokens with a digit are preferred over plain hyphenated words."""
    candidates = [c for c in SKU_RE.findall(text.upper()) if c not in _NOT_SKUS and not ORDER_RE.fullmatch(c)]
    with_digit = [c for c in candidates if any(ch.isdigit() for ch in c)]
    return (with_digit or candidates or [None])[0]


def find_email(text: str) -> str | None:
    match = EMAIL_RE.search(text)
    return match.group(0) if match else None


def heuristic_plan(message: str, memory: dict[str, Any]) -> Plan:
    order = find_order_number(message)
    sku = find_sku(message)
    email = find_email(message)
    fields: dict[str, Any] = {
        "order_number": order,
        "email": email,
        "sku": sku,
        "product_query": None,
        "quantity": None,
        "max_price": None,
        "knowledge_query": None,
        "translation_en": None,
        "translation_fr": None,
        "translation_ar": None,
        "ticket_summary": None,
        "urgent": False,
    }

    if memory.get("offered_human") and _YES.search(message):
        return Plan(
            intent="human_handoff",
            tools=["escalate_to_human"],
            **{**fields, "ticket_summary": "Customer accepted the offer to talk to a person"},
        )
    if _HUMAN.search(message):
        return Plan(intent="human_handoff", tools=["escalate_to_human"], **{**fields, "ticket_summary": message[:200]})
    if _GREETING.match(message):
        return Plan(intent="greeting", tools=[], **fields)
    if order or (_ORDER_WORDS.search(message) and memory.get("last_order_number") and not _TICKET.search(message)):
        fields["order_number"] = order or memory.get("last_order_number")
        return Plan(intent="order_status", tools=["get_order_status"], **fields)
    if _TICKET.search(message):
        return Plan(
            intent="create_ticket",
            tools=["create_support_ticket"],
            **{**fields, "ticket_summary": message[:200], "knowledge_query": message},
        )
    if _STOCK.search(message):
        return Plan(
            intent="stock",
            tools=["check_stock"],
            **{**fields, "product_query": None if sku else message, "sku": sku or memory.get("last_sku")},
        )
    if _PRICE.search(message) and not _PRICE_CHANGE.search(message):
        return Plan(
            intent="product_info",
            tools=["get_product_details"],
            **{**fields, "product_query": None if sku else message, "knowledge_query": message},
        )
    if _SEARCH.search(message):
        return Plan(intent="product_search", tools=["search_products"], **{**fields, "product_query": message})
    return Plan(intent="policy", tools=[], **{**fields, "knowledge_query": message})
