"""Chat service: one customer turn from request to persisted reply.

Loads the conversation (inside the caller's tenant), runs the graph, then stores the user message,
the reply with its sources/products/flags, the model calls and the conversation memory.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph import AgentDeps, agent_graph
from app.config import get_settings
from app.errors import Forbidden, NotFound
from app.llm.client import LLMClient, get_llm
from app.logs import get_logger
from app.models import (
    Conversation,
    ConversationStatus,
    Customer,
    LLMCall,
    Message,
    MessageRole,
    Shop,
    SupportTicket,
)
from app.observability import tracer
from app.tools.business import registry as default_registry
from app.tools.registry import ToolContext, ToolRegistry

log = get_logger("chat")


@dataclass
class ChatReply:
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    answer: str
    language: str
    outcome: str
    sources: list[dict[str, Any]] = field(default_factory=list)
    products: list[dict[str, Any]] = field(default_factory=list)
    latency_ms: int = 0
    tier: str | None = None
    model: str | None = None
    escalated: bool = False
    debug: dict[str, Any] = field(default_factory=dict)


def shop_facts(shop: Shop, language: str) -> dict[str, Any]:
    lang = language.split("-")[0]
    return {
        "id": str(shop.id),
        "slug": shop.slug,
        "name": shop.name,
        "currency": shop.currency,
        "support_email": shop.support_email,
        "handoff_sla_hours": shop.handoff_sla_hours,
        "support_hours": shop.support_hours.get(lang) or shop.support_hours.get("en", ""),
    }


async def _history(session: AsyncSession, conversation: Conversation, turns: int) -> list[dict[str, str]]:
    rows = (
        await session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation.id, Message.shop_id == conversation.shop_id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(turns * 2)
        )
    ).all()
    return [
        {"role": "user" if m.role == MessageRole.USER else "assistant", "content": m.content} for m in reversed(rows)
    ]


async def handle_turn(
    session: AsyncSession,
    *,
    shop: Shop,
    conversation_id: uuid.UUID,
    customer_id: uuid.UUID | None,
    text: str,
    actor: str = "widget",
    scopes: frozenset[str],
    llm: LLMClient | None = None,
    registry: ToolRegistry | None = None,
    use_llm: bool = True,
    request_id: str = "",
) -> ChatReply:
    settings = get_settings()
    started = time.perf_counter()
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None or conversation.shop_id != shop.id:
        raise NotFound("Conversation not found.")
    if conversation.customer_id != customer_id:
        raise Forbidden("This conversation belongs to another visitor.")

    customer = await session.get(Customer, customer_id) if customer_id else None
    history = await _history(session, conversation, settings.history_turns)
    user_msg = Message(shop_id=shop.id, conversation_id=conversation.id, role=MessageRole.USER, content=text[:4000])
    session.add(user_msg)
    await session.flush()

    tickets = (
        await session.scalars(
            select(SupportTicket.id).where(
                SupportTicket.shop_id == shop.id,
                SupportTicket.conversation_id == conversation.id,
                SupportTicket.is_escalation.is_(False),
            )
        )
    ).all()
    ctx = ToolContext(
        shop_id=shop.id,
        actor=actor,
        scopes=scopes,
        customer_id=customer_id,
        conversation_id=conversation.id,
        verified_orders=set(conversation.verified_orders or []),
        failed_verifications=conversation.failed_verifications,
        request_id=request_id,
        message_id=user_msg.id,
        tickets_created=len(tickets),
    )
    deps = AgentDeps(
        session=session,
        ctx=ctx,
        shop=shop_facts(shop, conversation.language or shop.default_language),
        llm=llm or get_llm(),
        registry=registry or default_registry,
        settings=settings,
        prior_language=conversation.language,
        customer_email=customer.email if customer else None,
        use_llm=use_llm,
    )

    with tracer.span(
        "chat_turn",
        as_type="agent",
        input={"message": text},
        metadata={"shop": shop.slug, "conversation_id": str(conversation.id), "channel": actor},
    ) as span:
        state = await agent_graph.ainvoke(
            {"message": text, "history": history, "memory": dict(conversation.memory or {})}, context=deps
        )
        span.update(output={"answer": state["answer"], "outcome": state["outcome"]})
        trace_id = tracer.current_trace_id()

    # Shop facts depend on the detected language (support hours wording).
    language = state["language"] if not state.get("dialect") else f"{state['language']}-{state['dialect']}"
    usages = state.get("usages", [])
    successful = [u for u in usages if u["success"]]
    retrieval = state.get("retrieval") or {}
    chunks = {c["source_id"]: c for c in retrieval.get("chunks", [])}
    cited = [chunks[s] for s in state.get("source_ids", []) if s in chunks]
    if (
        not cited
        and state["outcome"] == "answered"
        and retrieval
        and retrieval["confidence"] >= retrieval["threshold"]
        and not any(r["ok"] for r in state.get("tool_results", []))
    ):
        cited = list(chunks.values())[:2]
    sources = [
        {
            "id": c["source_id"],
            "document_id": c["document_id"],
            "title": c["title"],
            "heading": c["heading"],
            "snippet": c["content"][:400],
            "score": c["rerank_score"],
        }
        for c in cited
    ]

    latency_ms = int((time.perf_counter() - started) * 1000)
    reply = Message(
        shop_id=shop.id,
        conversation_id=conversation.id,
        role=MessageRole.ASSISTANT,
        content=state["answer"],
        language=language,
        latency_ms=latency_ms,
        model=successful[-1]["model"] if successful else None,
        tier=state.get("route", {}).get("tier"),
        prompt_tokens=sum(u["prompt_tokens"] for u in usages),
        completion_tokens=sum(u["completion_tokens"] for u in usages),
        cost_usd=Decimal(str(round(sum(u["cost_usd"] for u in usages), 6))),
        confidence=retrieval.get("confidence"),
        outcome=state["outcome"],
        sources=sources,
        products=state.get("products", []),
        flags={
            "guard": state.get("guard"),
            "route": state.get("route"),
            "plan": state.get("plan"),
            "plan_source": state.get("plan_source"),
            "validation": state.get("validation"),
            "degraded": state.get("degraded", False),
            "tools": [
                {"tool": r["tool"], "status": r["status"], "error": r.get("error")}
                for r in state.get("tool_results", [])
            ],
            "retrieval": {k: retrieval.get(k) for k in ("query", "confidence", "candidates", "latency_ms")}
            if retrieval
            else None,
        },
        trace_id=trace_id,
    )
    session.add(reply)
    for u in usages:
        session.add(
            LLMCall(
                shop_id=shop.id,
                conversation_id=conversation.id,
                purpose=u["purpose"],
                provider=u["provider"],
                model=u["model"],
                tier=u["tier"],
                prompt_tokens=u["prompt_tokens"],
                completion_tokens=u["completion_tokens"],
                cost_usd=Decimal(str(u["cost_usd"])),
                latency_ms=u["latency_ms"],
                success=u["success"],
                fallback_used=u["fallback_used"],
                error=u["error"],
            )
        )

    memory = dict(conversation.memory or {})
    memory["offered_human"] = state["outcome"] == "unknown"
    for r in state.get("tool_results", []):
        if r["ok"] and r["tool"] == "get_order_status":
            memory["last_order_number"] = r["data"]["order_number"]
        if r["ok"] and r["tool"] in ("get_product_details", "check_stock"):
            memory["last_sku"], memory["last_product_name"] = r["data"]["sku"], r["data"]["name"]
        if r["ok"] and r["tool"] == "search_products" and r["data"]["results"] and "last_sku" not in memory:
            memory["last_sku"] = r["data"]["results"][0]["sku"]
    conversation.memory = memory
    conversation.language = language
    conversation.message_count = (conversation.message_count or 0) + 2
    conversation.last_message_at = datetime.now(UTC)
    escalated = state["outcome"] == "escalated"
    if escalated:
        conversation.status = ConversationStatus.ESCALATED
    await session.flush()
    log.info(
        "chat_turn",
        shop=shop.slug,
        outcome=state["outcome"],
        language=language,
        latency_ms=latency_ms,
        tier=reply.tier,
        plan_source=state.get("plan_source"),
    )
    return ChatReply(
        conversation_id=conversation.id,
        message_id=reply.id,
        answer=state["answer"],
        language=language,
        outcome=state["outcome"],
        sources=sources,
        products=state.get("products", []),
        latency_ms=latency_ms,
        tier=reply.tier,
        model=reply.model,
        escalated=escalated,
        debug={
            "plan": state.get("plan"),
            "tools": reply.flags["tools"],
            "validation": state.get("validation"),
            "guard": state.get("guard"),
            "route": state.get("route"),
            "retrieval": retrieval,
            "plan_source": state.get("plan_source"),
            "usages": usages,
            "evidence": state.get("evidence", ""),
            "tool_results": state.get("tool_results", []),
        },
    )
