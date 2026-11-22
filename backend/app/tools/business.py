"""The shop tools. All queries are parameterised SQLAlchemy statements filtered on the caller's shop
(row-level security filters a second time). Tools return only what a customer may see: no address,
phone, internal ids or other customers' data."""

from __future__ import annotations

import hmac
import secrets
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import (
    Conversation,
    ConversationStatus,
    Customer,
    Inventory,
    Order,
    OrderItem,
    Product,
    Shop,
    SupportTicket,
    TicketCategory,
    TicketPriority,
    ToolCallStatus,
)
from app.rag.embeddings import get_embedder
from app.rag.retrieval import retrieve
from app.tools.registry import ToolContext, ToolError, ToolRegistry, ToolSpec
from app.tools.schemas import (
    CheckStockArgs,
    CreateTicketArgs,
    EscalateArgs,
    GetOrderStatusArgs,
    SearchKnowledgeArgs,
    SearchProductsArgs,
    SkuArgs,
)

MAX_TICKETS_PER_CONVERSATION = 3
PRODUCT_MIN_SIMILARITY = 0.40

STATUS_LABELS: dict[str, dict[str, str]] = {
    "pending": {
        "en": "awaiting payment confirmation",
        "fr": "en attente de confirmation du paiement",
        "ar": "في انتظار تأكيد الدفع",
    },
    "paid": {"en": "paid, being prepared", "fr": "payée, en préparation", "ar": "مدفوع، قيد التحضير"},
    "processing": {
        "en": "being prepared in our warehouse",
        "fr": "en préparation dans notre entrepôt",
        "ar": "قيد التحضير في المستودع",
    },
    "shipped": {"en": "shipped", "fr": "expédiée", "ar": "تم الشحن"},
    "out_for_delivery": {
        "en": "out for delivery",
        "fr": "en cours de livraison",
        "ar": "في الطريق إليك مع الموزع",
    },
    "delivered": {"en": "delivered", "fr": "livrée", "ar": "تم التسليم"},
    "cancelled": {"en": "cancelled", "fr": "annulée", "ar": "ملغى"},
    "returned": {"en": "returned", "fr": "retournée", "ar": "تم الإرجاع"},
    "refunded": {"en": "refunded", "fr": "remboursée", "ar": "تم استرجاع المبلغ"},
}
STOCK_LABELS = {
    "in_stock": {"en": "in stock", "fr": "en stock", "ar": "متوفر"},
    "low_stock": {"en": "low stock", "fr": "stock faible", "ar": "كمية محدودة"},
    "out_of_stock": {"en": "out of stock", "fr": "en rupture de stock", "ar": "غير متوفر حاليًا"},
}


def _lang(ctx: ToolContext) -> str:
    return ctx.language.split("-")[0] if ctx.language.split("-")[0] in ("en", "fr", "ar") else "en"


def _name(product: Product, lang: str) -> str:
    return product.name_i18n.get(lang) or product.name_i18n.get("en") or product.sku


def _money(value: Any) -> str:
    return f"{value:.3f}"


def _stock_status(inv: Inventory | None) -> str:
    if inv is None or inv.quantity_available <= 0:
        return "out_of_stock"
    return "low_stock" if inv.quantity_available <= inv.low_stock_threshold else "in_stock"


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def _product_by_sku(session: AsyncSession, ctx: ToolContext, sku: str) -> tuple[Product, Inventory | None]:
    row = (
        await session.execute(
            select(Product, Inventory)
            .outerjoin(Inventory, (Inventory.product_id == Product.id) & (Inventory.shop_id == Product.shop_id))
            .where(Product.shop_id == ctx.shop_id, Product.sku == sku, Product.is_active.is_(True))
        )
    ).first()
    if row is None:
        raise ToolError(ToolCallStatus.NOT_FOUND, "product_not_found", {"sku": sku})
    return row[0], row[1]


# ----------------------------------------------------------------------------------- catalogue ----
async def search_products(session: AsyncSession, args: SearchProductsArgs, ctx: ToolContext) -> dict[str, Any]:
    lang = _lang(ctx)
    base = (
        select(Product, Inventory)
        .outerjoin(Inventory, (Inventory.product_id == Product.id) & (Inventory.shop_id == Product.shop_id))
        .where(Product.shop_id == ctx.shop_id, Product.is_active.is_(True))
    )
    if args.category:
        base = base.where(Product.category == args.category.lower())
    if args.max_price:
        base = base.where(Product.price <= args.max_price)
    if args.in_stock_only:
        base = base.where(Inventory.quantity_available > 0)

    pattern = f"%{_escape_like(args.query)}%"
    lexical_score = func.word_similarity(args.query, Product.search_text)
    lexical = (
        await session.execute(
            base.where(or_(Product.search_text.ilike(pattern, escape="\\"), lexical_score > 0.35))
            .order_by(lexical_score.desc())
            .limit(10)
        )
    ).all()

    vector = await get_embedder().embed_query(args.query)
    distance = Product.embedding.cosine_distance(vector)
    semantic = (
        await session.execute(base.where(distance <= 1 - PRODUCT_MIN_SIMILARITY).order_by(distance).limit(10))
    ).all()

    scores: dict[str, float] = {}
    rows: dict[str, tuple[Product, Inventory | None]] = {}
    for ranked in (lexical, semantic):
        for rank, (product, inv) in enumerate(ranked, start=1):
            scores[product.sku] = scores.get(product.sku, 0.0) + 1 / (60 + rank)
            rows[product.sku] = (product, inv)
    ordered = sorted(scores, key=scores.__getitem__, reverse=True)[: args.limit]
    results = []
    for sku in ordered:
        product, inv = rows[sku]
        status = _stock_status(inv)
        results.append(
            {
                "sku": product.sku,
                "name": _name(product, lang),
                "brand": product.brand,
                "category": product.category,
                "price": _money(product.price),
                "currency": product.currency,
                "stock_status": status,
            }
        )
    return {"query": args.query, "count": len(results), "results": results}


async def get_product_details(session: AsyncSession, args: SkuArgs, ctx: ToolContext) -> dict[str, Any]:
    lang = _lang(ctx)
    product, inv = await _product_by_sku(session, ctx, args.sku)
    status = _stock_status(inv)
    return {
        "sku": product.sku,
        "name": _name(product, lang),
        "brand": product.brand,
        "category": product.category,
        "description": product.description_i18n.get(lang) or product.description_i18n.get("en", ""),
        "price": _money(product.price),
        "currency": product.currency,
        "specs": product.specs,
        "warranty_months": product.warranty_months,
        "stock_status": status,
        "stock_label": STOCK_LABELS[status][lang],
    }


async def check_stock(session: AsyncSession, args: CheckStockArgs, ctx: ToolContext) -> dict[str, Any]:
    lang = _lang(ctx)
    product, inv = await _product_by_sku(session, ctx, args.sku)
    status = _stock_status(inv)
    available = inv.quantity_available if inv else 0
    return {
        "sku": product.sku,
        "name": _name(product, lang),
        "stock_status": status,
        "stock_label": STOCK_LABELS[status][lang],
        # Exact counts are shown only when stock is low ("only 3 left").
        "quantity_available": available if status == "low_stock" else None,
        "requested_quantity": args.quantity,
        "requested_quantity_available": available >= args.quantity,
        # None means no confirmed date: the assistant must say it does not know.
        "restock_date": inv.restock_date.isoformat() if inv and inv.restock_date and status == "out_of_stock" else None,
    }


# -------------------------------------------------------------------------------------- orders ----
async def _authorise_order(
    session: AsyncSession, ctx: ToolContext, order_number: str, email: str | None
) -> tuple[Order, Customer]:
    """Return the order only if the caller may see it. Missing and not-yours look identical."""
    settings = get_settings()
    if ctx.failed_verifications >= settings.order_verification_max_failures:
        raise ToolError(ToolCallStatus.DENIED, "verification_locked")
    row = (
        await session.execute(
            select(Order, Customer)
            .join(Customer, (Customer.id == Order.customer_id) & (Customer.shop_id == Order.shop_id))
            .where(Order.shop_id == ctx.shop_id, Order.order_number == order_number)
        )
    ).first()
    order, customer = (row[0], row[1]) if row else (None, None)

    if "orders:read:any" in ctx.scopes and order is not None and customer is not None:
        return order, customer
    if order is not None and customer is not None:
        if ctx.customer_id is not None and order.customer_id == ctx.customer_id:
            return order, customer
        if order_number in ctx.verified_orders:
            return order, customer
    if email is None:
        if ctx.customer_id is not None:
            # Signed-in customer asking about an order that is not theirs (or does not exist).
            raise ToolError(ToolCallStatus.NOT_FOUND, "order_not_found_for_customer")
        raise ToolError(
            ToolCallStatus.DENIED, "verification_required", {"needs": "the e-mail address used for the order"}
        )
    # Constant-time comparison; same answer whether the order exists or the e-mail is wrong.
    expected = (customer.email if customer else "nobody@invalid").strip().lower()
    if order is not None and hmac.compare_digest(expected.encode(), email.strip().lower().encode()):
        ctx.verified_orders.add(order_number)
        if ctx.conversation_id:
            await session.execute(
                update(Conversation)
                .where(Conversation.id == ctx.conversation_id)
                .values(verified_orders=sorted(ctx.verified_orders))
            )
        assert customer is not None
        return order, customer
    ctx.failed_verifications += 1
    if ctx.conversation_id:
        await session.execute(
            update(Conversation)
            .where(Conversation.id == ctx.conversation_id)
            .values(failed_verifications=ctx.failed_verifications)
        )
    raise ToolError(ToolCallStatus.DENIED, "verification_failed")


async def get_order_status(session: AsyncSession, args: GetOrderStatusArgs, ctx: ToolContext) -> dict[str, Any]:
    lang = _lang(ctx)
    order, _customer = await _authorise_order(session, ctx, args.order_number, args.email)
    items = (
        await session.execute(
            select(OrderItem.quantity, Product)
            .join(Product, (Product.id == OrderItem.product_id) & (Product.shop_id == OrderItem.shop_id))
            .where(OrderItem.order_id == order.id, OrderItem.shop_id == ctx.shop_id)
        )
    ).all()
    return {
        "order_number": order.order_number,
        "status": order.status.value,
        "status_label": STATUS_LABELS[order.status.value][lang],
        "placed_on": order.placed_at.date().isoformat(),
        "items": [{"sku": p.sku, "name": _name(p, lang), "quantity": qty} for qty, p in items],
        "total": _money(order.total_amount),
        "currency": order.currency,
        "shipping_method": order.shipping_method,
        "carrier": order.carrier,
        "tracking_number": order.tracking_number,
        # None = the carrier has not given a date yet. Never estimate one.
        "estimated_delivery_date": order.estimated_delivery_date.isoformat() if order.estimated_delivery_date else None,
        "delivered_on": order.delivered_at.date().isoformat() if order.delivered_at else None,
        "shipping_city": order.shipping_city,
    }


# ------------------------------------------------------------------------------------- tickets ----
async def _new_ticket_number(session: AsyncSession, ctx: ToolContext) -> str:
    for _ in range(10):
        number = f"T-{secrets.randbelow(10**6):06d}"
        exists = await session.scalar(
            select(SupportTicket.id).where(SupportTicket.shop_id == ctx.shop_id, SupportTicket.ticket_number == number)
        )
        if not exists:
            return number
    raise ToolError(ToolCallStatus.ERROR, "ticket_number_exhausted")


async def _contact_email(session: AsyncSession, ctx: ToolContext, provided: str | None) -> str | None:
    if ctx.customer_id:
        customer = await session.get(Customer, ctx.customer_id)
        if customer and customer.shop_id == ctx.shop_id:
            return customer.email
    return provided


async def _shop(session: AsyncSession, ctx: ToolContext) -> Shop:
    shop = await session.get(Shop, ctx.shop_id)
    assert shop is not None
    return shop


async def create_support_ticket(session: AsyncSession, args: CreateTicketArgs, ctx: ToolContext) -> dict[str, Any]:
    if ctx.tickets_created >= MAX_TICKETS_PER_CONVERSATION:
        raise ToolError(ToolCallStatus.DENIED, "ticket_limit_reached")
    email = await _contact_email(session, ctx, args.contact_email)
    if email is None:
        raise ToolError(
            ToolCallStatus.INVALID,
            "contact_email_required",
            {"needs": "an e-mail address so the team can reply"},
        )
    order_id = None
    if args.order_number:
        try:
            order, _ = await _authorise_order(session, ctx, args.order_number, args.contact_email)
            order_id = order.id
        except ToolError:
            order_id = None  # The ticket is still created, just not linked to an order we cannot verify.
    shop = await _shop(session, ctx)
    ticket = SupportTicket(
        shop_id=ctx.shop_id,
        ticket_number=await _new_ticket_number(session, ctx),
        conversation_id=ctx.conversation_id,
        customer_id=ctx.customer_id,
        order_id=order_id,
        subject=args.subject,
        description=args.description,
        category=TicketCategory(args.category),
        priority=TicketPriority.NORMAL,
        contact_email=email,
        language=ctx.language,
    )
    session.add(ticket)
    await session.flush()
    ctx.tickets_created += 1
    return {
        "ticket_number": ticket.ticket_number,
        "status": "open",
        "category": args.category,
        "linked_order": args.order_number if order_id else None,
        "reply_within_hours": shop.handoff_sla_hours,
        "reply_to": "e-mail",
    }


async def escalate_to_human(session: AsyncSession, args: EscalateArgs, ctx: ToolContext) -> dict[str, Any]:
    shop = await _shop(session, ctx)
    lang = _lang(ctx)
    if ctx.conversation_id:
        existing = await session.scalar(
            select(SupportTicket).where(
                SupportTicket.shop_id == ctx.shop_id,
                SupportTicket.conversation_id == ctx.conversation_id,
                SupportTicket.is_escalation.is_(True),
            )
        )
        if existing:
            return {
                "ticket_number": existing.ticket_number,
                "already_escalated": True,
                "reply_within_hours": shop.handoff_sla_hours,
                "support_hours": shop.support_hours.get(lang, shop.support_hours.get("en")),
            }
    email = await _contact_email(session, ctx, args.contact_email)
    ticket = SupportTicket(
        shop_id=ctx.shop_id,
        ticket_number=await _new_ticket_number(session, ctx),
        conversation_id=ctx.conversation_id,
        customer_id=ctx.customer_id,
        subject="Conversation handed over to a human agent",
        description=args.reason,
        category=TicketCategory.OTHER,
        priority=TicketPriority.HIGH if args.urgency == "high" else TicketPriority.NORMAL,
        contact_email=email,
        is_escalation=True,
        language=ctx.language,
    )
    session.add(ticket)
    if ctx.conversation_id:
        await session.execute(
            update(Conversation)
            .where(Conversation.id == ctx.conversation_id)
            .values(status=ConversationStatus.ESCALATED)
        )
    await session.flush()
    return {
        "ticket_number": ticket.ticket_number,
        "already_escalated": False,
        "reply_within_hours": shop.handoff_sla_hours,
        "support_hours": shop.support_hours.get(lang, shop.support_hours.get("en")),
        "reply_channel": "e-mail" if email else "this chat",
    }


# ----------------------------------------------------------------------------------- knowledge ----
async def search_knowledge_base(session: AsyncSession, args: SearchKnowledgeArgs, ctx: ToolContext) -> dict[str, Any]:
    result = await retrieve(session, ctx.shop_id, args.query, ctx.language, top_k=args.top_k)
    return {
        "query": args.query,
        "confidence": round(result.confidence, 3),
        "answerable": result.answerable,
        "sources": [c.as_source() for c in result.chunks] if result.answerable else [],
    }


def build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    for spec in [
        ToolSpec(
            "search_products",
            "Search the shop catalogue by keywords, category or budget.",
            SearchProductsArgs,
            "catalog:read",
            search_products,
        ),
        ToolSpec(
            "get_product_details",
            "Get price, specifications, warranty and availability for one SKU.",
            SkuArgs,
            "catalog:read",
            get_product_details,
        ),
        ToolSpec(
            "check_stock",
            "Check live stock for one SKU, optionally for a quantity.",
            CheckStockArgs,
            "catalog:read",
            check_stock,
        ),
        ToolSpec(
            "get_order_status",
            "Get the status of an order. Signed-in customers see only their own "
            "orders; guests must give the e-mail address used for the order.",
            GetOrderStatusArgs,
            "orders:lookup",
            get_order_status,
        ),
        ToolSpec(
            "create_support_ticket",
            "Open a support ticket for the customer.",
            CreateTicketArgs,
            "tickets:create",
            create_support_ticket,
            read_only=False,
        ),
        ToolSpec(
            "escalate_to_human",
            "Hand the conversation over to a human support agent.",
            EscalateArgs,
            "handoff",
            escalate_to_human,
            read_only=False,
        ),
        ToolSpec(
            "search_knowledge_base",
            "Search the shop's policies, FAQ and product documents.",
            SearchKnowledgeArgs,
            "kb:read",
            search_knowledge_base,
        ),
    ]:
        registry.register(spec)
    return registry


registry = build_registry()


def utcnow() -> datetime:
    return datetime.now(UTC)
