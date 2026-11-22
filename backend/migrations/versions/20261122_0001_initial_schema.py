"""Initial schema: tenants, catalogue, orders, conversations, knowledge base, evaluations.

Also enables pgvector/pg_trgm, row-level security on every tenant table and grants for the
application role.

Revision ID: 0001
Revises:
Create Date: 2026-11-22 12:57:55.865692
"""

from collections.abc import Sequence

import pgvector.sqlalchemy.vector
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.config import get_settings
from app.models import TENANT_TABLES

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _app_role() -> str:
    from sqlalchemy.engine import make_url

    return make_url(get_settings().database_url).username or "support_app"


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("trigger", sa.String(length=32), nullable=False),
        sa.Column("git_sha", sa.String(length=40), nullable=True),
        sa.Column("dataset_version", sa.String(length=64), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("total_cases", sa.Integer(), nullable=False),
        sa.Column("passed_cases", sa.Integer(), nullable=False),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "rate_limit_buckets",
        sa.Column("key", sa.String(length=200), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("key", "window_start"),
    )
    op.create_table(
        "shops",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("default_language", sa.String(length=8), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("support_email", sa.String(length=320), nullable=False),
        sa.Column("support_hours", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("handoff_sla_hours", sa.Integer(), nullable=False),
        sa.Column("allowed_origins", postgresql.ARRAY(sa.String(length=255)), nullable=False),
        sa.Column("widget_secret", sa.String(length=128), nullable=False),
        sa.Column("theme", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("is_demo", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "customers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("external_ref", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("preferred_language", sa.String(length=8), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("shop_id", "email", name="uq_customers_shop_email"),
        sa.UniqueConstraint("shop_id", "external_ref", name="uq_customers_shop_external_ref"),
        sa.UniqueConstraint("shop_id", "id", name="uq_customers_shop_id_id"),
    )
    op.create_index(op.f("ix_customers_shop_id"), "customers", ["shop_id"], unique=False)
    op.create_table(
        "evaluation_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.String(length=64), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("scores", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("failure_reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["evaluation_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "case_id", name="uq_eval_results_run_case"),
    )
    op.create_index(op.f("ix_evaluation_results_run_id"), "evaluation_results", ["run_id"], unique=False)
    op.create_table(
        "products",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("name_i18n", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("description_i18n", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("brand", sa.String(length=100), nullable=False),
        sa.Column("price", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("specs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("warranty_months", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=384), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("price >= 0", name="ck_products_price_positive"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("shop_id", "id", name="uq_products_shop_id_id"),
        sa.UniqueConstraint("shop_id", "sku", name="uq_products_shop_sku"),
    )
    op.create_index(op.f("ix_products_category"), "products", ["category"], unique=False)
    op.create_index(
        "ix_products_embedding",
        "products",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        "ix_products_search_trgm",
        "products",
        ["search_text"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"search_text": "gin_trgm_ops"},
    )
    op.create_index(op.f("ix_products_shop_id"), "products", ["shop_id"], unique=False)
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "role",
            sa.Enum("admin", "agent", "viewer", name="user_role", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index(op.f("ix_users_shop_id"), "users", ["shop_id"], unique=False)
    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=True),
        sa.Column(
            "channel",
            sa.Enum("widget", "web", "api", name="channel", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("language", sa.String(length=8), nullable=True),
        sa.Column(
            "status",
            sa.Enum("open", "resolved", "escalated", name="conversation_status", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("message_count", sa.Integer(), nullable=False),
        sa.Column("verified_orders", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("failed_verifications", sa.Integer(), nullable=False),
        sa.Column("memory", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["shop_id", "customer_id"],
            ["customers.shop_id", "customers.id"],
            name="fk_conversations_customer",
            ondelete="SET NULL (customer_id)",
        ),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("shop_id", "id", name="uq_conversations_shop_id_id"),
    )
    op.create_index("ix_conversations_shop_started", "conversations", ["shop_id", "started_at"], unique=False)
    op.create_index("ix_conversations_shop_status", "conversations", ["shop_id", "status"], unique=False)
    op.create_table(
        "inventory",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("quantity_available", sa.Integer(), nullable=False),
        sa.Column("low_stock_threshold", sa.Integer(), nullable=False),
        sa.Column("restock_date", sa.Date(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("quantity_available >= 0", name="ck_inventory_qty_positive"),
        sa.ForeignKeyConstraint(
            ["shop_id", "product_id"],
            ["products.shop_id", "products.id"],
            name="fk_inventory_product",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("shop_id", "product_id", name="uq_inventory_shop_product"),
    )
    op.create_index(op.f("ix_inventory_shop_id"), "inventory", ["shop_id"], unique=False)
    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("doc_type", sa.String(length=32), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "processing",
                "ready",
                "failed",
                name="document_status",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("error", sa.String(length=500), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("quarantined_chunks", sa.Integer(), nullable=False),
        sa.Column("uploaded_by", sa.Uuid(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_content", sa.LargeBinary(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("shop_id", "id", name="uq_documents_shop_id_id"),
        sa.UniqueConstraint("shop_id", "sha256", name="uq_documents_shop_sha256"),
    )
    op.create_index("ix_documents_shop_status", "knowledge_documents", ["shop_id", "status"], unique=False)
    op.create_table(
        "orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("order_number", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "paid",
                "processing",
                "shipped",
                "out_for_delivery",
                "delivered",
                "cancelled",
                "returned",
                "refunded",
                name="order_status",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("placed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_amount", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("shipping_method", sa.String(length=64), nullable=False),
        sa.Column("carrier", sa.String(length=64), nullable=True),
        sa.Column("tracking_number", sa.String(length=64), nullable=True),
        sa.Column("estimated_delivery_date", sa.Date(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("shipping_city", sa.String(length=100), nullable=False),
        sa.Column("shipping_address", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["shop_id", "customer_id"],
            ["customers.shop_id", "customers.id"],
            name="fk_orders_customer",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("shop_id", "id", name="uq_orders_shop_id_id"),
        sa.UniqueConstraint("shop_id", "order_number", name="uq_orders_shop_number"),
    )
    op.create_index("ix_orders_shop_customer", "orders", ["shop_id", "customer_id"], unique=False)
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("heading", sa.String(length=300), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=False),
        sa.Column("ts_config", postgresql.REGCONFIG(), server_default="simple", nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("quarantined", sa.Boolean(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=384), nullable=False),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(
                "setweight(to_tsvector('simple', coalesce(heading, '')), 'A') || to_tsvector(ts_config, content) || to_tsvector('simple', content)",
                persisted=True,
            ),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["shop_id", "document_id"],
            ["knowledge_documents.shop_id", "knowledge_documents.id"],
            name="fk_chunks_document",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_chunks_document_index"),
    )
    op.create_index(
        "ix_chunks_embedding",
        "document_chunks",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        "ix_chunks_search_vector", "document_chunks", ["search_vector"], unique=False, postgresql_using="gin"
    )
    op.create_index("ix_chunks_shop", "document_chunks", ["shop_id"], unique=False)
    op.create_table(
        "llm_calls",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("tier", sa.String(length=16), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("fallback_used", sa.Boolean(), nullable=False),
        sa.Column("error", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_llm_calls_conversation_id"), "llm_calls", ["conversation_id"], unique=False)
    op.create_index("ix_llm_calls_shop_created", "llm_calls", ["shop_id", "created_at"], unique=False)
    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column(
            "role",
            sa.Enum("user", "assistant", "human_agent", name="message_role", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("tier", sa.String(length=16), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=True),
        sa.Column("sources", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("products", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("flags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["shop_id", "conversation_id"],
            ["conversations.shop_id", "conversations.id"],
            name="fk_messages_conversation",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_messages_conversation_created", "messages", ["conversation_id", "created_at"], unique=False)
    op.create_index("ix_messages_shop_created", "messages", ["shop_id", "created_at"], unique=False)
    op.create_table(
        "order_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_order_items_qty_positive"),
        sa.ForeignKeyConstraint(
            ["shop_id", "order_id"],
            ["orders.shop_id", "orders.id"],
            name="fk_order_items_order",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["shop_id", "product_id"], ["products.shop_id", "products.id"], name="fk_order_items_product"
        ),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_order_items_order_id"), "order_items", ["order_id"], unique=False)
    op.create_index(op.f("ix_order_items_product_id"), "order_items", ["product_id"], unique=False)
    op.create_table(
        "support_tickets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("ticket_number", sa.String(length=32), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("customer_id", sa.Uuid(), nullable=True),
        sa.Column("order_id", sa.Uuid(), nullable=True),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "category",
            sa.Enum(
                "order",
                "product",
                "return",
                "warranty",
                "payment",
                "other",
                name="ticket_category",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "priority",
            sa.Enum("low", "normal", "high", "urgent", name="ticket_priority", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("open", "pending", "resolved", "closed", name="ticket_status", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("contact_email", sa.String(length=320), nullable=True),
        sa.Column("is_escalation", sa.Boolean(), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["shop_id", "conversation_id"],
            ["conversations.shop_id", "conversations.id"],
            name="fk_tickets_conversation",
            ondelete="SET NULL (conversation_id)",
        ),
        sa.ForeignKeyConstraint(
            ["shop_id", "customer_id"],
            ["customers.shop_id", "customers.id"],
            name="fk_tickets_customer",
            ondelete="SET NULL (customer_id)",
        ),
        sa.ForeignKeyConstraint(
            ["shop_id", "order_id"],
            ["orders.shop_id", "orders.id"],
            name="fk_tickets_order",
            ondelete="SET NULL (order_id)",
        ),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("shop_id", "ticket_number", name="uq_tickets_shop_number"),
    )
    op.create_index("ix_tickets_shop_status", "support_tickets", ["shop_id", "status"], unique=False)
    op.create_table(
        "tool_calls",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("message_id", sa.Uuid(), nullable=True),
        sa.Column("tool_name", sa.String(length=64), nullable=False),
        sa.Column("actor", sa.String(length=32), nullable=False),
        sa.Column("arguments", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "success",
                "not_found",
                "denied",
                "invalid",
                "error",
                name="tool_call_status",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tool_calls_conversation_id"), "tool_calls", ["conversation_id"], unique=False)
    op.create_index("ix_tool_calls_shop_created", "tool_calls", ["shop_id", "created_at"], unique=False)

    # Current tenant, set per transaction by the application (app/db.py). Empty -> NULL -> no rows.
    op.execute(
        "CREATE FUNCTION app_current_shop() RETURNS uuid LANGUAGE sql STABLE AS "
        "$$ SELECT NULLIF(current_setting('app.shop_id', true), '')::uuid $$"
    )
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (shop_id = app_current_shop()) WITH CHECK (shop_id = app_current_shop())"
        )

    role = _app_role()
    exists = op.get_bind().execute(sa.text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}).scalar()
    if exists:
        op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "{role}"')
        op.execute(f'GRANT EXECUTE ON FUNCTION app_current_shop() TO "{role}"')
        # The app role may read shops (widget lookup) but never change tenants or staff accounts.
        op.execute(f'REVOKE INSERT, UPDATE, DELETE ON shops FROM "{role}"')
        op.execute(f'REVOKE DELETE ON users FROM "{role}"')
        op.execute(f'REVOKE ALL ON alembic_version FROM "{role}"')


def downgrade() -> None:
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_index("ix_tool_calls_shop_created", table_name="tool_calls")
    op.drop_index(op.f("ix_tool_calls_conversation_id"), table_name="tool_calls")
    op.drop_table("tool_calls")
    op.drop_index("ix_tickets_shop_status", table_name="support_tickets")
    op.drop_table("support_tickets")
    op.drop_index(op.f("ix_order_items_product_id"), table_name="order_items")
    op.drop_index(op.f("ix_order_items_order_id"), table_name="order_items")
    op.drop_table("order_items")
    op.drop_index("ix_messages_shop_created", table_name="messages")
    op.drop_index("ix_messages_conversation_created", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_llm_calls_shop_created", table_name="llm_calls")
    op.drop_index(op.f("ix_llm_calls_conversation_id"), table_name="llm_calls")
    op.drop_table("llm_calls")
    op.drop_index("ix_chunks_shop", table_name="document_chunks")
    op.drop_index("ix_chunks_search_vector", table_name="document_chunks", postgresql_using="gin")
    op.drop_index(
        "ix_chunks_embedding",
        table_name="document_chunks",
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_table("document_chunks")
    op.drop_index("ix_orders_shop_customer", table_name="orders")
    op.drop_table("orders")
    op.drop_index("ix_documents_shop_status", table_name="knowledge_documents")
    op.drop_table("knowledge_documents")
    op.drop_index(op.f("ix_inventory_shop_id"), table_name="inventory")
    op.drop_table("inventory")
    op.drop_index("ix_conversations_shop_status", table_name="conversations")
    op.drop_index("ix_conversations_shop_started", table_name="conversations")
    op.drop_table("conversations")
    op.drop_index(op.f("ix_users_shop_id"), table_name="users")
    op.drop_table("users")
    op.drop_index(op.f("ix_products_shop_id"), table_name="products")
    op.drop_index(
        "ix_products_search_trgm",
        table_name="products",
        postgresql_using="gin",
        postgresql_ops={"search_text": "gin_trgm_ops"},
    )
    op.drop_index(
        "ix_products_embedding",
        table_name="products",
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_index(op.f("ix_products_category"), table_name="products")
    op.drop_table("products")
    op.drop_index(op.f("ix_evaluation_results_run_id"), table_name="evaluation_results")
    op.drop_table("evaluation_results")
    op.drop_index(op.f("ix_customers_shop_id"), table_name="customers")
    op.drop_table("customers")
    op.drop_table("shops")
    op.drop_table("rate_limit_buckets")
    op.drop_table("evaluation_runs")
    op.execute("DROP FUNCTION IF EXISTS app_current_shop()")
