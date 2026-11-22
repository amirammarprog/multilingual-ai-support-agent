"""Customer-facing endpoints: widget configuration, chat sessions, messages, voice and hand-off."""

from __future__ import annotations

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import Field
from sqlalchemy import select

from app.agent.service import handle_turn
from app.api.deps import Session, Widget, client_ip, origin_cache
from app.api.schemas import (
    ChatRequest,
    ChatResponse,
    EscalateRequest,
    MessageOut,
    SessionRequest,
    SessionResponse,
    SpeakRequest,
    StrictModel,
    TranscriptOut,
    WidgetConfig,
)
from app.config import get_settings
from app.db import bind_shop
from app.errors import Forbidden, NotFound
from app.models import Channel, Conversation, Customer, Message, Shop
from app.security import rate_limit
from app.security.auth import issue_widget_token, verify_customer_identity
from app.tools.business import registry
from app.tools.registry import WIDGET_SCOPES, ToolContext
from app.voice.providers import get_stt, get_tts, validate_audio

router = APIRouter(prefix="/api/v1", tags=["chat"])


async def _shop_by_slug(session: Session, slug: str) -> Shop:
    shop = await session.scalar(select(Shop).where(Shop.slug == slug))
    if shop is None:
        raise NotFound("Unknown shop.")
    return shop


@router.get("/widget/config", response_model=WidgetConfig, summary="Public widget configuration for a shop")
async def widget_config(shop: str, session: Session) -> WidgetConfig:
    record = await _shop_by_slug(session, shop)
    settings = get_settings()
    return WidgetConfig(
        shop=record.slug,
        name=record.name,
        languages=["ar", "fr", "en"],
        default_language=record.default_language,
        theme=record.theme or {},
        support_hours=record.support_hours or {},
        voice={"stt": settings.stt_provider != "disabled", "tts": settings.tts_provider},
    )


@router.post(
    "/widget/sessions",
    response_model=SessionResponse,
    status_code=201,
    summary="Start a chat session (optionally as a customer vouched for by the shop)",
)
async def create_session(body: SessionRequest, request: Request, session: Session) -> SessionResponse:
    settings = get_settings()
    await rate_limit.hit(f"session:{rate_limit.hash_ip(client_ip(request))}", settings.rate_limit_session_create_per_ip)
    shop = await _shop_by_slug(session, body.shop)
    await origin_cache.refresh()
    if not origin_cache.allowed(str(shop.id), request.headers.get("origin")):
        raise Forbidden("This website is not allowed to use this shop's assistant.")
    await bind_shop(session, shop.id)

    customer = None
    if body.customer_token:
        external_ref = verify_customer_identity(body.customer_token, shop.widget_secret, shop.slug)
        customer = await session.scalar(
            select(Customer).where(Customer.shop_id == shop.id, Customer.external_ref == external_ref)
        )
        if customer is None:
            raise Forbidden("Unknown customer for this shop.")
    conversation = Conversation(
        shop_id=shop.id,
        customer_id=customer.id if customer else None,
        channel=Channel.WIDGET,
        language=body.language,
    )
    session.add(conversation)
    await session.commit()
    token = issue_widget_token(shop.id, conversation.id, customer.id if customer else None)
    return SessionResponse(
        session_token=token,
        conversation_id=conversation.id,
        expires_in=settings.widget_session_ttl_minutes * 60,
        customer_name=customer.full_name if customer else None,
        shop_name=shop.name,
    )


@router.post("/chat/messages", response_model=ChatResponse, summary="Send a customer message and get the reply")
async def send_message(body: ChatRequest, request: Request, widget: Widget, session: Session) -> ChatResponse:
    settings = get_settings()
    await rate_limit.hit(f"chat:session:{widget.claims.conversation_id}", settings.rate_limit_chat_per_session)
    await rate_limit.hit(f"chat:ip:{rate_limit.hash_ip(client_ip(request))}", settings.rate_limit_chat_per_ip)
    reply = await handle_turn(
        session,
        shop=widget.shop,
        conversation_id=widget.claims.conversation_id,
        customer_id=widget.claims.customer_id,
        text=body.message,
        actor="widget",
        scopes=WIDGET_SCOPES,
        request_id=getattr(request.state, "request_id", ""),
    )
    await session.commit()
    return ChatResponse(
        conversation_id=reply.conversation_id,
        message_id=reply.message_id,
        answer=reply.answer,
        language=reply.language,
        outcome=reply.outcome,
        sources=reply.sources,
        products=reply.products,
        latency_ms=reply.latency_ms,
        escalated=reply.escalated,
    )


@router.get("/chat/messages", response_model=list[MessageOut], summary="Conversation history (incl. human replies)")
async def list_messages(widget: Widget, session: Session) -> list[MessageOut]:
    rows = (
        await session.scalars(
            select(Message)
            .where(Message.conversation_id == widget.claims.conversation_id, Message.shop_id == widget.shop.id)
            .order_by(Message.created_at)
        )
    ).all()
    return [
        MessageOut(
            id=m.id,
            role=m.role.value,
            content=m.content,
            language=m.language,
            created_at=m.created_at,
            sources=m.sources or [],
            products=m.products or [],
            outcome=m.outcome,
        )
        for m in rows
    ]


@router.post("/chat/escalate", summary="The visitor pressed 'talk to a person'")
async def escalate(body: EscalateRequest, widget: Widget, session: Session) -> dict:
    conversation = await session.get(Conversation, widget.claims.conversation_id)
    if conversation is None:
        raise NotFound("Conversation not found.")
    ctx = ToolContext(
        shop_id=widget.shop.id,
        actor="widget",
        scopes=WIDGET_SCOPES,
        customer_id=widget.claims.customer_id,
        conversation_id=conversation.id,
        language=conversation.language or widget.shop.default_language,
    )
    args = {"reason": body.reason or "Visitor pressed the 'talk to a person' button", "urgency": "normal"}
    if body.contact_email:
        args["contact_email"] = body.contact_email
    result = await registry.execute(session, "escalate_to_human", args, ctx)
    await session.commit()
    if not result.ok:
        return JSONResponse({"ok": False, "error": result.error_code}, status_code=400)
    return {"ok": True, **(result.data or {})}


@router.post("/voice/transcribe", response_model=TranscriptOut, summary="Speech to text for the widget")
async def transcribe(request: Request, widget: Widget, audio: UploadFile = File(...)) -> TranscriptOut:
    settings = get_settings()
    await rate_limit.hit(f"voice:{widget.claims.conversation_id}", settings.rate_limit_chat_per_session)
    data = await audio.read(5 * 1024 * 1024 + 1)
    content_type = validate_audio(data, audio.content_type or "")
    transcript = await get_stt().transcribe(data, content_type, request.headers.get("x-language-hint"))
    return TranscriptOut(
        text=transcript.text,
        language=transcript.language,
        duration_seconds=transcript.duration_seconds,
        provider=transcript.provider,
    )


@router.post("/voice/speak", summary="Text to speech (or instructions to use the browser voice)")
async def speak(body: SpeakRequest, widget: Widget) -> Response:
    settings = get_settings()
    await rate_limit.hit(f"tts:{widget.claims.conversation_id}", settings.rate_limit_chat_per_session)
    speech = await get_tts().synthesize(body.text, body.language)
    if speech is None:
        return JSONResponse({"provider": "browser", "text": body.text, "language": body.language})
    return Response(content=speech.audio, media_type=speech.media_type)


# --------------------------------------------------------------------------------- demo only ----
demo = APIRouter(prefix="/api/v1/demo", tags=["demo"])


class DemoIdentityRequest(StrictModel):
    shop: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9-]+$")
    external_ref: str = Field(min_length=1, max_length=64)


@demo.get("/customers", summary="Fictional demo customers (DEMO_MODE only)")
async def demo_customers(shop: str, session: Session) -> list[dict]:
    record = await _shop_by_slug(session, shop)
    if not (get_settings().demo_mode and record.is_demo):
        raise NotFound("Not available.")
    await bind_shop(session, record.id)
    rows = (
        await session.scalars(select(Customer).where(Customer.shop_id == record.id).order_by(Customer.external_ref))
    ).all()
    return [{"external_ref": c.external_ref, "name": c.full_name} for c in rows]


@demo.post("/identity", summary="Sign a customer identity token like a shop backend would (DEMO_MODE only)")
async def demo_identity(body: DemoIdentityRequest, session: Session) -> dict:
    from app.security.auth import sign_customer_identity

    record = await _shop_by_slug(session, body.shop)
    if not (get_settings().demo_mode and record.is_demo):
        raise NotFound("Not available.")
    return {"customer_token": sign_customer_identity(record.widget_secret, record.slug, body.external_ref)}
