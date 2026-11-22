"""Tool argument schemas.

``extra="forbid"`` matters for security: a model (or an MCP client) that adds ``shop_id``,
``customer_id`` or ``price`` to a call gets a validation error. Identity and tenant always come
from the server-side session, never from tool arguments.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

OrderNumber = Annotated[str, Field(min_length=4, max_length=16, description="Order number, e.g. BC-10421")]
Sku = Annotated[str, Field(min_length=3, max_length=32, description="Product SKU, e.g. ORB-X5-128")]

_ORDER_RE = re.compile(r"^[A-Z]{2}-\d{4,6}$")
_SKU_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{2,31}$")


class ToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _order(value: str) -> str:
    value = value.upper().replace(" ", "")
    if not _ORDER_RE.match(value):
        raise ValueError("order number must look like BC-10421")
    return value


def _sku(value: str) -> str:
    value = value.upper().replace(" ", "-")
    if not _SKU_RE.match(value):
        raise ValueError("invalid SKU")
    return value


class SearchProductsArgs(ToolArgs):
    query: str = Field(min_length=1, max_length=200, description="What the customer is looking for")
    category: str | None = Field(default=None, max_length=64)
    max_price: float | None = Field(default=None, gt=0, le=1_000_000)
    in_stock_only: bool = False
    limit: int = Field(default=5, ge=1, le=8)


class SkuArgs(ToolArgs):
    sku: Sku

    @field_validator("sku")
    @classmethod
    def _norm_sku(cls, v: str) -> str:
        return _sku(v)


class CheckStockArgs(SkuArgs):
    quantity: int = Field(default=1, ge=1, le=100)


class GetOrderStatusArgs(ToolArgs):
    order_number: OrderNumber
    email: EmailStr | None = Field(
        default=None, description="E-mail used for the order. Needed only when the visitor is not signed in."
    )

    @field_validator("order_number")
    @classmethod
    def _norm_order(cls, v: str) -> str:
        return _order(v)


class CreateTicketArgs(ToolArgs):
    subject: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=5, max_length=2000)
    category: Literal["order", "product", "return", "warranty", "payment", "other"] = "other"
    order_number: OrderNumber | None = None
    contact_email: EmailStr | None = Field(default=None, description="Required when the visitor is not signed in")

    @field_validator("order_number")
    @classmethod
    def _norm_order(cls, v: str | None) -> str | None:
        return _order(v) if v else None


class EscalateArgs(ToolArgs):
    reason: str = Field(min_length=3, max_length=500)
    urgency: Literal["normal", "high"] = "normal"
    contact_email: EmailStr | None = None


class SearchKnowledgeArgs(ToolArgs):
    query: str = Field(min_length=2, max_length=500)
    top_k: int = Field(default=4, ge=1, le=6)
