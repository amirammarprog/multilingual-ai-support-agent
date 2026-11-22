"""ORM models.

Every tenant table carries ``shop_id``. Child rows reference parents through composite foreign keys
``(shop_id, parent_id)``, so the database itself refuses a row that points at another shop's data.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, ClassVar

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, REGCONFIG, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

EMBEDDING_DIM = 384


def new_id() -> uuid.UUID:
    return uuid.uuid7()


def _enum(cls: type[StrEnum], name: str) -> Enum:
    return Enum(cls, name=name, native_enum=False, length=32, values_callable=lambda e: [m.value for m in e])


class Base(DeclarativeBase):
    type_annotation_map: ClassVar[dict[Any, Any]] = {dict[str, Any]: JSONB, list[Any]: JSONB}


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# --------------------------------------------------------------------------------------- enums ----
class UserRole(StrEnum):
    ADMIN = "admin"
    AGENT = "agent"
    VIEWER = "viewer"


class OrderStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    RETURNED = "returned"
    REFUNDED = "refunded"


class ConversationStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    ESCALATED = "escalated"


class Channel(StrEnum):
    WIDGET = "widget"
    WEB = "web"
    API = "api"


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    HUMAN_AGENT = "human_agent"


class TicketStatus(StrEnum):
    OPEN = "open"
    PENDING = "pending"
    RESOLVED = "resolved"
    CLOSED = "closed"


class TicketPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class TicketCategory(StrEnum):
    ORDER = "order"
    PRODUCT = "product"
    RETURN = "return"
    WARRANTY = "warranty"
    PAYMENT = "payment"
    OTHER = "other"


class DocumentStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class ToolCallStatus(StrEnum):
    SUCCESS = "success"
    NOT_FOUND = "not_found"
    DENIED = "denied"
    INVALID = "invalid"
    ERROR = "error"


# --------------------------------------------------------------------------------------- shops ----
class Shop(TimestampMixin, Base):
    __tablename__ = "shops"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    default_language: Mapped[str] = mapped_column(String(8), default="en")
    currency: Mapped[str] = mapped_column(String(3))
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    support_email: Mapped[str] = mapped_column(String(320))
    # Opening hours and hand-off delay per language; quoted verbatim, never paraphrased into promises.
    support_hours: Mapped[dict[str, Any]] = mapped_column(default=dict)
    handoff_sla_hours: Mapped[int] = mapped_column(Integer, default=24)
    allowed_origins: Mapped[list[str]] = mapped_column(ARRAY(String(255)), default=list)
    # HMAC secret the shop's own backend uses to sign customer identity tokens. Never returned by the API.
    widget_secret: Mapped[str] = mapped_column(String(128))
    theme: Mapped[dict[str, Any]] = mapped_column(default=dict)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class User(TimestampMixin, Base):
    """Shop staff who sign in to the admin console."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    full_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(_enum(UserRole, "user_role"), default=UserRole.AGENT)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Customer(TimestampMixin, Base):
    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("shop_id", "id", name="uq_customers_shop_id_id"),
        UniqueConstraint("shop_id", "email", name="uq_customers_shop_email"),
        UniqueConstraint("shop_id", "external_ref", name="uq_customers_shop_external_ref"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), index=True)
    external_ref: Mapped[str] = mapped_column(String(64))
    email: Mapped[str] = mapped_column(String(320))
    full_name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(32))
    preferred_language: Mapped[str | None] = mapped_column(String(8))


# ------------------------------------------------------------------------------------ catalogue ----
class Product(TimestampMixin, Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("shop_id", "id", name="uq_products_shop_id_id"),
        UniqueConstraint("shop_id", "sku", name="uq_products_shop_sku"),
        CheckConstraint("price >= 0", name="ck_products_price_positive"),
        Index(
            "ix_products_search_trgm",
            "search_text",
            postgresql_using="gin",
            postgresql_ops={"search_text": "gin_trgm_ops"},
        ),
        Index(
            "ix_products_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), index=True)
    sku: Mapped[str] = mapped_column(String(64))
    # {"en": "...", "fr": "...", "ar": "..."}
    name_i18n: Mapped[dict[str, Any]] = mapped_column()
    description_i18n: Mapped[dict[str, Any]] = mapped_column(default=dict)
    category: Mapped[str] = mapped_column(String(64), index=True)
    brand: Mapped[str] = mapped_column(String(100))
    price: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    currency: Mapped[str] = mapped_column(String(3))
    specs: Mapped[dict[str, Any]] = mapped_column(default=dict)
    warranty_months: Mapped[int] = mapped_column(Integer, default=12)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Denormalised names/brand/sku in every language, for trigram search.
    search_text: Mapped[str] = mapped_column(Text, default="")
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))


class Inventory(Base):
    __tablename__ = "inventory"
    __table_args__ = (
        UniqueConstraint("shop_id", "product_id", name="uq_inventory_shop_product"),
        ForeignKeyConstraint(
            ["shop_id", "product_id"],
            ["products.shop_id", "products.id"],
            ondelete="CASCADE",
            name="fk_inventory_product",
        ),
        CheckConstraint("quantity_available >= 0", name="ck_inventory_qty_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[uuid.UUID] = mapped_column()
    quantity_available: Mapped[int] = mapped_column(Integer, default=0)
    low_stock_threshold: Mapped[int] = mapped_column(Integer, default=5)
    # Only set when the supplier confirmed a date; the agent never guesses one.
    restock_date: Mapped[date | None] = mapped_column(Date)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# --------------------------------------------------------------------------------------- orders ----
class Order(TimestampMixin, Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("shop_id", "id", name="uq_orders_shop_id_id"),
        UniqueConstraint("shop_id", "order_number", name="uq_orders_shop_number"),
        ForeignKeyConstraint(
            ["shop_id", "customer_id"],
            ["customers.shop_id", "customers.id"],
            ondelete="CASCADE",
            name="fk_orders_customer",
        ),
        Index("ix_orders_shop_customer", "shop_id", "customer_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"))
    customer_id: Mapped[uuid.UUID] = mapped_column()
    order_number: Mapped[str] = mapped_column(String(32))
    status: Mapped[OrderStatus] = mapped_column(_enum(OrderStatus, "order_status"))
    placed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    currency: Mapped[str] = mapped_column(String(3))
    shipping_method: Mapped[str] = mapped_column(String(64))
    carrier: Mapped[str | None] = mapped_column(String(64))
    tracking_number: Mapped[str | None] = mapped_column(String(64))
    # Only present when the carrier gave one.
    estimated_delivery_date: Mapped[date | None] = mapped_column(Date)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    shipping_city: Mapped[str] = mapped_column(String(100))
    shipping_address: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["shop_id", "order_id"],
            ["orders.shop_id", "orders.id"],
            ondelete="CASCADE",
            name="fk_order_items_order",
        ),
        ForeignKeyConstraint(
            ["shop_id", "product_id"], ["products.shop_id", "products.id"], name="fk_order_items_product"
        ),
        CheckConstraint("quantity > 0", name="ck_order_items_qty_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"))
    order_id: Mapped[uuid.UUID] = mapped_column(index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(index=True)
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 3))


# -------------------------------------------------------------------------------- conversations ----
class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("shop_id", "id", name="uq_conversations_shop_id_id"),
        ForeignKeyConstraint(
            ["shop_id", "customer_id"],
            ["customers.shop_id", "customers.id"],
            ondelete="SET NULL (customer_id)",
            name="fk_conversations_customer",
        ),
        Index("ix_conversations_shop_started", "shop_id", "started_at"),
        Index("ix_conversations_shop_status", "shop_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"))
    customer_id: Mapped[uuid.UUID | None] = mapped_column()
    channel: Mapped[Channel] = mapped_column(_enum(Channel, "channel"), default=Channel.WIDGET)
    language: Mapped[str | None] = mapped_column(String(8))
    status: Mapped[ConversationStatus] = mapped_column(
        _enum(ConversationStatus, "conversation_status"), default=ConversationStatus.OPEN
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_message_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    # Order numbers a guest proved ownership of (order number + email), kept server side.
    verified_orders: Mapped[list[Any]] = mapped_column(default=list)
    failed_verifications: Mapped[int] = mapped_column(Integer, default=0)
    # Entities from earlier turns (last order / product discussed) to resolve follow-up questions.
    memory: Mapped[dict[str, Any]] = mapped_column(default=dict)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["shop_id", "conversation_id"],
            ["conversations.shop_id", "conversations.id"],
            ondelete="CASCADE",
            name="fk_messages_conversation",
        ),
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
        Index("ix_messages_shop_created", "shop_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"))
    conversation_id: Mapped[uuid.UUID] = mapped_column()
    role: Mapped[MessageRole] = mapped_column(_enum(MessageRole, "message_role"))
    content: Mapped[str] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    model: Mapped[str | None] = mapped_column(String(128))
    tier: Mapped[str | None] = mapped_column(String(16))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal(0))
    confidence: Mapped[float | None] = mapped_column(Float)
    outcome: Mapped[str | None] = mapped_column(String(32))
    sources: Mapped[list[Any]] = mapped_column(default=list)
    products: Mapped[list[Any]] = mapped_column(default=list)
    flags: Mapped[dict[str, Any]] = mapped_column(default=dict)
    trace_id: Mapped[str | None] = mapped_column(String(64))


class ToolCall(Base):
    """Audit log of every tool execution attempt, including the denied ones."""

    __tablename__ = "tool_calls"
    __table_args__ = (Index("ix_tool_calls_shop_created", "shop_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"))
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"))
    tool_name: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(32))
    arguments: Mapped[dict[str, Any]] = mapped_column(default=dict)
    status: Mapped[ToolCallStatus] = mapped_column(_enum(ToolCallStatus, "tool_call_status"))
    error_code: Mapped[str | None] = mapped_column(String(64))
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LLMCall(Base):
    """One row per model call: the basis for model-usage, latency and cost dashboards."""

    __tablename__ = "llm_calls"
    __table_args__ = (Index("ix_llm_calls_shop_created", "shop_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"))
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    purpose: Mapped[str] = mapped_column(String(32))
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    tier: Mapped[str] = mapped_column(String(16))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal(0))
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SupportTicket(TimestampMixin, Base):
    __tablename__ = "support_tickets"
    __table_args__ = (
        UniqueConstraint("shop_id", "ticket_number", name="uq_tickets_shop_number"),
        ForeignKeyConstraint(
            ["shop_id", "conversation_id"],
            ["conversations.shop_id", "conversations.id"],
            ondelete="SET NULL (conversation_id)",
            name="fk_tickets_conversation",
        ),
        ForeignKeyConstraint(
            ["shop_id", "customer_id"],
            ["customers.shop_id", "customers.id"],
            ondelete="SET NULL (customer_id)",
            name="fk_tickets_customer",
        ),
        ForeignKeyConstraint(
            ["shop_id", "order_id"],
            ["orders.shop_id", "orders.id"],
            ondelete="SET NULL (order_id)",
            name="fk_tickets_order",
        ),
        Index("ix_tickets_shop_status", "shop_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"))
    ticket_number: Mapped[str] = mapped_column(String(32))
    conversation_id: Mapped[uuid.UUID | None] = mapped_column()
    customer_id: Mapped[uuid.UUID | None] = mapped_column()
    order_id: Mapped[uuid.UUID | None] = mapped_column()
    subject: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[TicketCategory] = mapped_column(_enum(TicketCategory, "ticket_category"))
    priority: Mapped[TicketPriority] = mapped_column(_enum(TicketPriority, "ticket_priority"))
    status: Mapped[TicketStatus] = mapped_column(_enum(TicketStatus, "ticket_status"), default=TicketStatus.OPEN)
    contact_email: Mapped[str | None] = mapped_column(String(320))
    is_escalation: Mapped[bool] = mapped_column(Boolean, default=False)
    language: Mapped[str | None] = mapped_column(String(8))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ------------------------------------------------------------------------------------ knowledge ----
class KnowledgeDocument(TimestampMixin, Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        UniqueConstraint("shop_id", "id", name="uq_documents_shop_id_id"),
        UniqueConstraint("shop_id", "sha256", name="uq_documents_shop_sha256"),
        Index("ix_documents_shop_status", "shop_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(255))
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    doc_type: Mapped[str] = mapped_column(String(32), default="other")
    language: Mapped[str | None] = mapped_column(String(8))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[DocumentStatus] = mapped_column(
        _enum(DocumentStatus, "document_status"), default=DocumentStatus.PENDING
    )
    error: Mapped[str | None] = mapped_column(String(500))
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    quarantined_chunks: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Raw file kept so a document can be re-indexed after a chunking/embedding change.
    raw_content: Mapped[bytes | None] = mapped_column(deferred=True)


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["shop_id", "document_id"],
            ["knowledge_documents.shop_id", "knowledge_documents.id"],
            ondelete="CASCADE",
            name="fk_chunks_document",
        ),
        UniqueConstraint("document_id", "chunk_index", name="uq_chunks_document_index"),
        Index(
            "ix_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_chunks_search_vector", "search_vector", postgresql_using="gin"),
        Index("ix_chunks_shop", "shop_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"))
    document_id: Mapped[uuid.UUID] = mapped_column()
    chunk_index: Mapped[int] = mapped_column(Integer)
    heading: Mapped[str] = mapped_column(String(300), default="")
    content: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(8))
    ts_config: Mapped[str] = mapped_column(REGCONFIG, server_default="simple")
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    # Chunks that look like instructions to the model (indirect prompt injection) are never retrieved.
    quarantined: Mapped[bool] = mapped_column(Boolean, default=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))
    search_vector: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('simple', coalesce(heading, '')), 'A') || "
            "to_tsvector(ts_config, content) || to_tsvector('simple', content)",
            persisted=True,
        ),
    )


# ---------------------------------------------------------------------------------- evaluation ----
class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="running")
    mode: Mapped[str] = mapped_column(String(16))  # "full" (agent + judge) or "offline" (no LLM)
    trigger: Mapped[str] = mapped_column(String(32), default="local")
    git_sha: Mapped[str | None] = mapped_column(String(40))
    dataset_version: Mapped[str] = mapped_column(String(64))
    config: Mapped[dict[str, Any]] = mapped_column(default=dict)
    total_cases: Mapped[int] = mapped_column(Integer, default=0)
    passed_cases: Mapped[int] = mapped_column(Integer, default=0)
    metrics: Mapped[dict[str, Any]] = mapped_column(default=dict)


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"
    __table_args__ = (UniqueConstraint("run_id", "case_id", name="uq_eval_results_run_case"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluation_runs.id", ondelete="CASCADE"), index=True)
    case_id: Mapped[str] = mapped_column(String(64))
    language: Mapped[str] = mapped_column(String(8))
    category: Mapped[str] = mapped_column(String(32))
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text, default="")
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    scores: Mapped[dict[str, Any]] = mapped_column(default=dict)
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)
    failure_reasons: Mapped[list[Any]] = mapped_column(default=list)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal(0))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RateLimitBucket(Base):
    """Fixed-window counters shared by all API replicas."""

    __tablename__ = "rate_limit_buckets"

    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)


TENANT_TABLES = [
    "customers",
    "products",
    "inventory",
    "orders",
    "order_items",
    "conversations",
    "messages",
    "tool_calls",
    "llm_calls",
    "support_tickets",
    "knowledge_documents",
    "document_chunks",
]
