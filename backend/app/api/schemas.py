"""Request and response models of the public API (they also drive the OpenAPI docs)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ------------------------------------------------------------------------------------- auth ----
class LoginRequest(StrictModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class ShopOut(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    currency: str
    default_language: str


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 - OAuth token type, not a secret
    expires_in: int
    user: UserOut
    shop: ShopOut


# ----------------------------------------------------------------------------------- widget ----
class WidgetConfig(BaseModel):
    shop: str
    name: str
    languages: list[str]
    default_language: str
    theme: dict[str, Any]
    support_hours: dict[str, str]
    voice: dict[str, Any]


class SessionRequest(StrictModel):
    shop: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9-]+$")
    customer_token: str | None = Field(default=None, max_length=4096)
    language: Literal["en", "fr", "ar"] | None = None


class SessionResponse(BaseModel):
    session_token: str
    conversation_id: uuid.UUID
    expires_in: int
    customer_name: str | None
    shop_name: str


class ChatRequest(StrictModel):
    message: str = Field(min_length=1, max_length=2000)


class Source(BaseModel):
    id: str
    document_id: str
    title: str
    heading: str
    snippet: str
    score: float


class ProductRef(BaseModel):
    sku: str
    name: str | None = None
    price: str | None = None
    currency: str | None = None
    stock_status: str | None = None


class ChatResponse(BaseModel):
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    answer: str
    language: str
    outcome: str
    sources: list[Source]
    products: list[ProductRef]
    latency_ms: int
    escalated: bool


class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    language: str | None
    created_at: datetime
    sources: list[dict[str, Any]] = []
    products: list[dict[str, Any]] = []
    outcome: str | None = None


class EscalateRequest(StrictModel):
    reason: str | None = Field(default=None, max_length=500)
    contact_email: EmailStr | None = None


class SpeakRequest(StrictModel):
    text: str = Field(min_length=1, max_length=2000)
    language: Literal["en", "fr", "ar", "ar-tn"] = "en"


class TranscriptOut(BaseModel):
    text: str
    language: str | None
    duration_seconds: float
    provider: str


# ------------------------------------------------------------------------------------ admin ----
class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    filename: str
    content_type: str
    doc_type: str
    language: str | None
    size_bytes: int
    status: str
    error: str | None
    chunk_count: int
    quarantined_chunks: int
    created_at: datetime
    processed_at: datetime | None


class HumanReply(StrictModel):
    content: str = Field(min_length=1, max_length=4000)


class SearchRequest(StrictModel):
    query: str = Field(min_length=2, max_length=500)
    language: Literal["en", "fr", "ar"] | None = None
