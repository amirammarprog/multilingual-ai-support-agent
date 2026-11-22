"""Test doubles and helpers for the agent's LLM path."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from app.agent.prompts import Answer, Plan
from app.agent.service import ChatReply, handle_turn
from app.db import tenant_session
from app.llm.client import LLMUsage
from app.models import Conversation, Customer, Shop
from app.tools.registry import WIDGET_SCOPES

PLAN_DEFAULTS: dict[str, Any] = {
    "intent": "policy",
    "tools": [],
    "order_number": None,
    "email": None,
    "product_query": None,
    "sku": None,
    "quantity": None,
    "max_price": None,
    "knowledge_query": None,
    "translation_en": None,
    "translation_fr": None,
    "translation_ar": None,
    "ticket_summary": None,
    "urgent": False,
}


def plan(**fields: Any) -> dict[str, Any]:
    return PLAN_DEFAULTS | fields


class ScriptedLLM:
    """Stands in for a model provider: returns pre-written plans/answers and records the prompts it got.
    Lets tests check what the backend does with *adversarial* model output (hallucinated numbers,
    invented order numbers, tools the user may not call)."""

    available = True

    def __init__(self, plans: list[dict[str, Any]], answers: list[dict[str, Any]] | None = None) -> None:
        self.plans = list(plans)
        self.answers = list(answers or [])
        self.prompts: list[list[dict[str, str]]] = []

    def describe(self) -> list[dict[str, str]]:
        return [{"provider": "scripted", "base_url": "test", "fast": "scripted", "smart": "scripted"}]

    async def structured(self, *, messages, schema, tier, purpose, max_tokens=400):
        self.prompts.append(messages)
        usage = LLMUsage(purpose, "scripted", "scripted-model", tier, prompt_tokens=50, completion_tokens=10)
        if schema is Plan:
            return Plan.model_validate(self.plans.pop(0)), [usage]
        return Answer.model_validate(self.answers.pop(0)), [usage]


async def run_turns(
    shop_slug: str,
    messages: list[str],
    *,
    customer_ref: str | None = None,
    llm: Any = None,
    use_llm: bool | None = None,
) -> list[ChatReply]:
    async with tenant_session(None) as session:
        shop = await session.scalar(select(Shop).where(Shop.slug == shop_slug))
    assert shop is not None
    replies = []
    async with tenant_session(shop.id) as session:
        customer = None
        if customer_ref:
            customer = await session.scalar(select(Customer).where(Customer.external_ref == customer_ref))
        conversation = Conversation(shop_id=shop.id, customer_id=customer.id if customer else None)
        session.add(conversation)
        await session.commit()
        for text in messages:
            reply = await handle_turn(
                session,
                shop=shop,
                conversation_id=conversation.id,
                customer_id=customer.id if customer else None,
                text=text,
                scopes=WIDGET_SCOPES,
                llm=llm,
                use_llm=use_llm if use_llm is not None else llm is not None,
            )
            await session.commit()
            replies.append(reply)
    return replies


def random_email() -> str:
    return f"visitor-{uuid.uuid4().hex[:8]}@example.org"
