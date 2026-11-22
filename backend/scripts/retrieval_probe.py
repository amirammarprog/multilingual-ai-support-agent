"""Print retrieval results for a few questions, with and without planner translations.

python scripts/retrieval_probe.py
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.db import tenant_session
from app.models import Shop
from app.rag.retrieval import retrieve

CASES = [
    ("return window for products", "en", {"fr": "délai de retour des produits", "ar": "مدة إرجاع المنتجات"}),
    (
        "Can I get a refund if the headphones are opened?",
        "en",
        {
            "fr": "Puis-je être remboursé si le casque a été ouvert ?",
            "ar": "هل يمكن استرجاع المال إذا تم فتح السماعات؟",
        },
    ),
    (
        "do you offer installments?",
        "en",
        {"fr": "proposez-vous le paiement en plusieurs fois ?", "ar": "هل يوجد دفع بالتقسيط؟"},
    ),
    (
        "Quel est le délai pour retourner un produit ?",
        "fr",
        {"en": "How long do I have to return a product?", "ar": "ما هي مدة إرجاع المنتج؟"},
    ),
    (
        "What will the weather be in Tokyo tomorrow?",
        "en",
        {"fr": "Quel temps fera-t-il à Tokyo demain ?", "ar": "كيف سيكون الطقس في طوكيو غدا؟"},
    ),
    ("Do you ship to Algeria?", "en", {"fr": "Livrez-vous en Algérie ?", "ar": "هل توصلون إلى الجزائر؟"}),
]


async def main() -> None:
    async with tenant_session(None) as session:
        shop = await session.scalar(select(Shop).where(Shop.slug == "demo-shop"))
    assert shop is not None
    async with tenant_session(shop.id) as session:
        for query, language, translations in CASES:
            for extra in (None, translations):
                r = await retrieve(session, shop.id, query, language, translations=extra)
                top = [(round(c.rerank_score, 2), c.title[:14], c.heading[-24:]) for c in r.chunks][:3]
                print(
                    "T" if extra else "-", query[:44].ljust(44), f"conf {r.confidence:.3f}", f"{r.latency_ms} ms", top
                )


if __name__ == "__main__":
    asyncio.run(main())
