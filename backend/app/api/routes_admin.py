"""Admin console endpoints. Every query runs in the signed-in user's shop (filter + row-level security)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, BackgroundTasks, File, Form, Query, Request, UploadFile
from sqlalchemy import Integer, case, cast, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Session, Staff, client_ip, require_role
from app.api.schemas import (
    DocumentOut,
    HumanReply,
    LoginRequest,
    LoginResponse,
    SearchRequest,
    ShopOut,
    UserOut,
)
from app.config import get_settings
from app.errors import NotFound, Unauthorized
from app.models import (
    Conversation,
    ConversationStatus,
    DocumentChunk,
    DocumentStatus,
    EvaluationRun,
    KnowledgeDocument,
    LLMCall,
    Message,
    MessageRole,
    Shop,
    SupportTicket,
    ToolCall,
    User,
    UserRole,
)
from app.rag.ingestion import create_document, process_document
from app.rag.retrieval import retrieve
from app.security import rate_limit
from app.security.auth import issue_staff_token, verify_password

router = APIRouter(prefix="/api/v1", tags=["admin"])
EDITORS = (UserRole.ADMIN, UserRole.AGENT)


# ------------------------------------------------------------------------------------- auth ----
@router.post("/auth/login", response_model=LoginResponse, tags=["auth"])
async def login(body: LoginRequest, request: Request, session: Session) -> LoginResponse:
    settings = get_settings()
    await rate_limit.hit(f"login:{rate_limit.hash_ip(client_ip(request))}", settings.rate_limit_login_per_ip)
    user = await session.scalar(select(User).where(User.email == body.email.lower()))
    if not verify_password(body.password, user.password_hash if user else None) or user is None or not user.is_active:
        raise Unauthorized("Invalid e-mail or password.")
    shop = await session.get(Shop, user.shop_id)
    assert shop is not None
    user.last_login_at = datetime.now(UTC)
    await session.commit()
    return LoginResponse(
        access_token=issue_staff_token(user.id, shop.id, user.role.value),
        expires_in=settings.staff_token_ttl_minutes * 60,
        user=UserOut(id=user.id, email=user.email, full_name=user.full_name, role=user.role.value),
        shop=ShopOut(
            id=shop.id,
            slug=shop.slug,
            name=shop.name,
            currency=shop.currency,
            default_language=shop.default_language,
        ),
    )


@router.get("/auth/me", tags=["auth"])
async def me(staff: Staff) -> dict[str, Any]:
    return {
        "user": UserOut(
            id=staff.user.id,
            email=staff.user.email,
            full_name=staff.user.full_name,
            role=staff.user.role.value,
        ),
        "shop": ShopOut(
            id=staff.shop.id,
            slug=staff.shop.slug,
            name=staff.shop.name,
            currency=staff.shop.currency,
            default_language=staff.shop.default_language,
        ),
    }


# --------------------------------------------------------------------------------- overview ----
@router.get("/admin/overview")
async def overview(staff: Staff, session: Session, days: int = Query(30, ge=1, le=365)) -> dict[str, Any]:
    shop_id = staff.shop.id
    since = datetime.now(UTC) - timedelta(days=days)
    conv = (
        await session.execute(
            select(
                func.count(),
                func.count().filter(Conversation.status == ConversationStatus.RESOLVED),
                func.count().filter(Conversation.status == ConversationStatus.ESCALATED),
                func.count().filter(Conversation.message_count > 0),
            ).where(Conversation.shop_id == shop_id, Conversation.started_at >= since)
        )
    ).one()
    replies = (
        await session.execute(
            select(
                func.count(),
                func.avg(Message.latency_ms),
                func.percentile_cont(0.95).within_group(Message.latency_ms),
                func.coalesce(func.sum(Message.cost_usd), 0),
                func.count().filter(Message.outcome == "unknown"),
                func.count().filter(Message.outcome == "refused"),
                func.count().filter(Message.outcome == "answered"),
            ).where(Message.shop_id == shop_id, Message.role == MessageRole.ASSISTANT, Message.created_at >= since)
        )
    ).one()
    models = (
        await session.execute(
            select(
                LLMCall.model,
                LLMCall.tier,
                func.count(),
                func.sum(LLMCall.prompt_tokens),
                func.sum(LLMCall.completion_tokens),
                func.sum(LLMCall.cost_usd),
                func.avg(LLMCall.latency_ms),
                func.sum(cast(LLMCall.fallback_used, Integer)),
                func.sum(case((LLMCall.success, 0), else_=1)),
            )
            .where(LLMCall.shop_id == shop_id, LLMCall.created_at >= since)
            .group_by(LLMCall.model, LLMCall.tier)
            .order_by(func.count().desc())
        )
    ).all()
    per_day = (
        await session.execute(
            select(
                func.date_trunc("day", Conversation.started_at).label("day"),
                func.count(),
                func.count().filter(Conversation.status == ConversationStatus.ESCALATED),
            )
            .where(Conversation.shop_id == shop_id, Conversation.started_at >= since)
            .group_by("day")
            .order_by("day")
        )
    ).all()
    languages = (
        await session.execute(
            select(Message.language, func.count())
            .where(Message.shop_id == shop_id, Message.role == MessageRole.ASSISTANT, Message.created_at >= since)
            .group_by(Message.language)
        )
    ).all()
    tools = (
        await session.execute(
            select(ToolCall.tool_name, ToolCall.status, func.count())
            .where(ToolCall.shop_id == shop_id, ToolCall.created_at >= since)
            .group_by(ToolCall.tool_name, ToolCall.status)
        )
    ).all()
    latest_eval = await session.scalar(
        select(EvaluationRun).where(EvaluationRun.status == "completed").order_by(EvaluationRun.started_at.desc())
    )
    return {
        "period_days": days,
        "conversations": {"total": conv[0], "resolved": conv[1], "escalated": conv[2], "active": conv[3]},
        "replies": {
            "total": replies[0],
            "avg_latency_ms": round(float(replies[1] or 0)),
            "p95_latency_ms": round(float(replies[2] or 0)),
            "cost_usd": float(replies[3] or 0),
            "unknown": replies[4],
            "refused": replies[5],
            "answered": replies[6],
        },
        "models": [
            {
                "model": m,
                "tier": t,
                "calls": c,
                "prompt_tokens": int(p or 0),
                "completion_tokens": int(o or 0),
                "cost_usd": float(cost or 0),
                "avg_latency_ms": round(float(lat or 0)),
                "fallback_calls": int(fb or 0),
                "failed_calls": int(failed or 0),
            }
            for m, t, c, p, o, cost, lat, fb, failed in models
        ],
        "per_day": [{"day": d.date().isoformat(), "conversations": c, "escalated": e} for d, c, e in per_day],
        "languages": [{"language": lang or "unknown", "replies": c} for lang, c in languages],
        "tools": [{"tool": name, "status": status.value, "calls": c} for name, status, c in tools],
        "latest_eval": _run_summary(latest_eval) if latest_eval else None,
    }


def _run_summary(run: EvaluationRun) -> dict[str, Any]:
    return {
        "id": str(run.id),
        "started_at": run.started_at.isoformat(),
        "mode": run.mode,
        "trigger": run.trigger,
        "total_cases": run.total_cases,
        "passed_cases": run.passed_cases,
        "overall": (run.metrics or {}).get("overall"),
        "config": run.config,
    }


# ---------------------------------------------------------------------------- conversations ----
@router.get("/admin/conversations")
async def list_conversations(
    staff: Staff,
    session: Session,
    status: ConversationStatus | None = None,
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    query = select(Conversation).where(Conversation.shop_id == staff.shop.id, Conversation.message_count > 0)
    if status:
        query = query.where(Conversation.status == status)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = (
        await session.scalars(query.order_by(Conversation.last_message_at.desc()).limit(limit).offset(offset))
    ).all()
    ids = [c.id for c in rows]
    previews: dict[uuid.UUID, str] = {}
    if ids:
        first = (
            await session.execute(
                select(Message.conversation_id, Message.content)
                .where(Message.conversation_id.in_(ids), Message.role == MessageRole.USER)
                .distinct(Message.conversation_id)
                .order_by(Message.conversation_id, Message.created_at)
            )
        ).all()
        previews = {cid: content[:140] for cid, content in first}
    return {
        "total": total,
        "items": [
            {
                "id": str(c.id),
                "status": c.status.value,
                "language": c.language,
                "channel": c.channel.value,
                "customer_id": str(c.customer_id) if c.customer_id else None,
                "message_count": c.message_count,
                "started_at": c.started_at.isoformat(),
                "last_message_at": c.last_message_at.isoformat(),
                "preview": previews.get(c.id, ""),
            }
            for c in rows
        ],
    }


async def _conversation(session: AsyncSession, shop_id: uuid.UUID, conversation_id: uuid.UUID) -> Conversation:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None or conversation.shop_id != shop_id:
        raise NotFound("Conversation not found.")
    return conversation


@router.get("/admin/conversations/{conversation_id}")
async def conversation_detail(conversation_id: uuid.UUID, staff: Staff, session: Session) -> dict[str, Any]:
    conversation = await _conversation(session, staff.shop.id, conversation_id)
    messages = (
        await session.scalars(
            select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at, Message.id)
        )
    ).all()
    tools = (
        await session.scalars(
            select(ToolCall)
            .where(ToolCall.conversation_id == conversation.id)
            .order_by(ToolCall.created_at, ToolCall.id)
        )
    ).all()
    tickets = (
        await session.scalars(select(SupportTicket).where(SupportTicket.conversation_id == conversation.id))
    ).all()
    llm = (
        await session.scalars(
            select(LLMCall).where(LLMCall.conversation_id == conversation.id).order_by(LLMCall.created_at)
        )
    ).all()
    return {
        "id": str(conversation.id),
        "status": conversation.status.value,
        "language": conversation.language,
        "channel": conversation.channel.value,
        "started_at": conversation.started_at.isoformat(),
        "customer_id": str(conversation.customer_id) if conversation.customer_id else None,
        "messages": [
            {
                "id": str(m.id),
                "role": m.role.value,
                "content": m.content,
                "language": m.language,
                "created_at": m.created_at.isoformat(),
                "latency_ms": m.latency_ms,
                "model": m.model,
                "tier": m.tier,
                "cost_usd": float(m.cost_usd or 0),
                "confidence": m.confidence,
                "outcome": m.outcome,
                "sources": m.sources,
                "products": m.products,
                "flags": m.flags,
                "prompt_tokens": m.prompt_tokens,
                "completion_tokens": m.completion_tokens,
            }
            for m in messages
        ],
        "tool_calls": [
            {
                "id": str(t.id),
                "message_id": str(t.message_id) if t.message_id else None,
                "tool": t.tool_name,
                "status": t.status.value,
                "error": t.error_code,
                "arguments": t.arguments,
                "latency_ms": t.latency_ms,
                "created_at": t.created_at.isoformat(),
            }
            for t in tools
        ],
        "tickets": [
            {
                "ticket_number": t.ticket_number,
                "subject": t.subject,
                "status": t.status.value,
                "priority": t.priority.value,
                "is_escalation": t.is_escalation,
                "created_at": t.created_at.isoformat(),
            }
            for t in tickets
        ],
        "llm_calls": [
            {
                "purpose": c.purpose,
                "provider": c.provider,
                "model": c.model,
                "tier": c.tier,
                "prompt_tokens": c.prompt_tokens,
                "completion_tokens": c.completion_tokens,
                "cost_usd": float(c.cost_usd or 0),
                "latency_ms": c.latency_ms,
                "success": c.success,
                "fallback_used": c.fallback_used,
            }
            for c in llm
        ],
    }


@router.post("/admin/conversations/{conversation_id}/reply", dependencies=[require_role(*EDITORS)])
async def human_reply(conversation_id: uuid.UUID, body: HumanReply, staff: Staff, session: Session) -> dict:
    conversation = await _conversation(session, staff.shop.id, conversation_id)
    message = Message(
        shop_id=staff.shop.id,
        conversation_id=conversation.id,
        role=MessageRole.HUMAN_AGENT,
        content=body.content,
        flags={"author": staff.user.full_name},
    )
    session.add(message)
    conversation.message_count += 1
    conversation.last_message_at = datetime.now(UTC)
    await session.commit()
    return {"id": str(message.id)}


@router.post("/admin/conversations/{conversation_id}/resolve", dependencies=[require_role(*EDITORS)])
async def resolve(conversation_id: uuid.UUID, staff: Staff, session: Session) -> dict:
    conversation = await _conversation(session, staff.shop.id, conversation_id)
    conversation.status = ConversationStatus.RESOLVED
    conversation.resolved_at = datetime.now(UTC)
    await session.commit()
    return {"status": conversation.status.value}


@router.get("/admin/tickets")
async def list_tickets(staff: Staff, session: Session, limit: int = Query(50, ge=1, le=200)) -> list[dict]:
    rows = (
        await session.scalars(
            select(SupportTicket)
            .where(SupportTicket.shop_id == staff.shop.id)
            .order_by(SupportTicket.created_at.desc())
            .limit(limit)
        )
    ).all()
    return [
        {
            "ticket_number": t.ticket_number,
            "subject": t.subject,
            "category": t.category.value,
            "priority": t.priority.value,
            "status": t.status.value,
            "is_escalation": t.is_escalation,
            "conversation_id": str(t.conversation_id) if t.conversation_id else None,
            "created_at": t.created_at.isoformat(),
        }
        for t in rows
    ]


# -------------------------------------------------------------------------------- knowledge ----
@router.get("/admin/documents", response_model=list[DocumentOut])
async def list_documents(staff: Staff, session: Session) -> list[KnowledgeDocument]:
    return list(
        (
            await session.scalars(
                select(KnowledgeDocument)
                .where(KnowledgeDocument.shop_id == staff.shop.id)
                .order_by(KnowledgeDocument.created_at.desc())
            )
        ).all()
    )


@router.post("/admin/documents", response_model=DocumentOut, status_code=202, dependencies=[require_role(*EDITORS)])
async def upload_document(
    staff: Staff,
    session: Session,
    background: BackgroundTasks,
    file: UploadFile = File(...),
    title: str | None = Form(default=None, max_length=255),
    doc_type: str | None = Form(default=None, max_length=32),
) -> KnowledgeDocument:
    limit = get_settings().max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    doc = await create_document(
        session,
        staff.shop.id,
        file.filename or "document",
        data,
        title=title,
        doc_type=doc_type,
        uploaded_by=staff.user.id,
    )
    await session.commit()
    background.add_task(process_document, staff.shop.id, doc.id)
    return doc


@router.post("/admin/documents/{document_id}/reindex", status_code=202, dependencies=[require_role(*EDITORS)])
async def reindex(document_id: uuid.UUID, staff: Staff, session: Session, background: BackgroundTasks) -> dict:
    doc = await session.get(KnowledgeDocument, document_id)
    if doc is None or doc.shop_id != staff.shop.id:
        raise NotFound("Document not found.")
    doc.status = DocumentStatus.PENDING
    await session.commit()
    background.add_task(process_document, staff.shop.id, doc.id)
    return {"status": "pending"}


@router.delete("/admin/documents/{document_id}", status_code=204, dependencies=[require_role(UserRole.ADMIN)])
async def delete_document(document_id: uuid.UUID, staff: Staff, session: Session) -> None:
    doc = await session.get(KnowledgeDocument, document_id)
    if doc is None or doc.shop_id != staff.shop.id:
        raise NotFound("Document not found.")
    await session.execute(
        delete(KnowledgeDocument).where(KnowledgeDocument.id == document_id, KnowledgeDocument.shop_id == staff.shop.id)
    )
    await session.commit()


@router.get("/admin/documents/{document_id}/chunks")
async def document_chunks(document_id: uuid.UUID, staff: Staff, session: Session) -> list[dict]:
    rows = (
        await session.scalars(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id, DocumentChunk.shop_id == staff.shop.id)
            .order_by(DocumentChunk.chunk_index)
        )
    ).all()
    return [
        {
            "index": c.chunk_index,
            "heading": c.heading,
            "content": c.content,
            "language": c.language,
            "tokens": c.token_count,
            "quarantined": c.quarantined,
        }
        for c in rows
    ]


@router.post("/admin/search", summary="Try the retrieval pipeline (hybrid search + rerank) on a query")
async def search(body: SearchRequest, staff: Staff, session: Session) -> dict:
    from app.language import detect_language

    language = body.language or detect_language(body.query).code
    result = await retrieve(session, staff.shop.id, body.query, language)
    return result.as_dict()
