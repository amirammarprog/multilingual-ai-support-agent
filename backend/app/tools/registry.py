"""Tool registry: the single gate between a model (or MCP client) and the shop's data.

Every call goes through ``execute``, which:
1. rejects unknown tools,
2. checks the caller's scopes (derived from the authenticated session, not from the model),
3. validates arguments with a strict schema (unknown fields such as ``shop_id`` are rejected),
4. runs the tool with a timeout inside the caller's tenant,
5. writes an audit row (arguments redacted) whatever the outcome.

Ownership checks that depend on the data itself (is this order yours?) live inside the tools.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.logs import get_logger
from app.models import ToolCall, ToolCallStatus
from app.security.redaction import redact

log = get_logger("tools")

Actor = Literal["widget", "staff", "mcp", "eval"]

# Scopes granted per kind of caller. Customers never get "orders:read:any".
WIDGET_SCOPES = frozenset({"catalog:read", "kb:read", "orders:lookup", "tickets:create", "handoff"})
STAFF_SCOPES = frozenset({"catalog:read", "kb:read", "orders:lookup", "orders:read:any", "tickets:create", "handoff"})
TOOL_TIMEOUT_SECONDS = 15


@dataclass
class ToolContext:
    shop_id: uuid.UUID
    actor: Actor
    scopes: frozenset[str]
    customer_id: uuid.UUID | None = None
    conversation_id: uuid.UUID | None = None
    verified_orders: set[str] = field(default_factory=set)
    failed_verifications: int = 0
    language: str = "en"
    request_id: str = ""
    message_id: uuid.UUID | None = None
    tickets_created: int = 0


@dataclass
class ToolResult:
    name: str
    status: ToolCallStatus
    data: dict[str, Any] | None = None
    error_code: str | None = None
    latency_ms: int = 0

    @property
    def ok(self) -> bool:
        return self.status == ToolCallStatus.SUCCESS

    def for_model(self) -> dict[str, Any]:
        """What the model sees: data on success, a machine-readable error otherwise."""
        if self.ok:
            return {"tool": self.name, "ok": True, "data": self.data}
        return {"tool": self.name, "ok": False, "error": self.error_code, "data": self.data or {}}


class ToolError(Exception):
    """Raised inside a tool to return a controlled, non-success status."""

    def __init__(self, status: ToolCallStatus, code: str, data: dict[str, Any] | None = None) -> None:
        super().__init__(code)
        self.status, self.code, self.data = status, code, data


Handler = Callable[[AsyncSession, Any, ToolContext], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    scope: str
    handler: Handler
    read_only: bool = True

    def json_schema(self) -> dict[str, Any]:
        schema = self.args_model.model_json_schema()
        schema.pop("title", None)
        return schema

    def as_mcp(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.json_schema(),
            "annotations": {"readOnlyHint": self.read_only},
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def available(self, scopes: frozenset[str]) -> list[ToolSpec]:
        return [t for t in self._tools.values() if t.scope in scopes]

    async def execute(
        self, session: AsyncSession, name: str, raw_args: dict[str, Any] | None, ctx: ToolContext
    ) -> ToolResult:
        started = time.perf_counter()
        spec = self._tools.get(name)
        args_for_audit = redact(raw_args or {})
        try:
            if spec is None:
                raise ToolError(ToolCallStatus.DENIED, "unknown_tool")
            if spec.scope not in ctx.scopes:
                raise ToolError(ToolCallStatus.DENIED, "insufficient_scope")
            if not isinstance(raw_args, dict | None):
                raise ToolError(ToolCallStatus.INVALID, "arguments_must_be_an_object")
            try:
                args = spec.args_model.model_validate(raw_args or {})
            except ValidationError as exc:
                fields = sorted({".".join(str(p) for p in e["loc"]) for e in exc.errors()})
                raise ToolError(ToolCallStatus.INVALID, "invalid_arguments", {"fields": fields}) from exc
            async with asyncio.timeout(TOOL_TIMEOUT_SECONDS):
                data = await spec.handler(session, args, ctx)
            result = ToolResult(name, ToolCallStatus.SUCCESS, data=data)
        except ToolError as exc:
            result = ToolResult(name, exc.status, data=exc.data, error_code=exc.code)
        except TimeoutError:
            result = ToolResult(name, ToolCallStatus.ERROR, error_code="timeout")
        except Exception:
            log.exception("tool_failed", tool=name)
            await session.rollback()
            result = ToolResult(name, ToolCallStatus.ERROR, error_code="internal_error")
        result.latency_ms = int((time.perf_counter() - started) * 1000)

        if result.status == ToolCallStatus.DENIED:
            log.warning("tool_denied", tool=name, code=result.error_code, actor=ctx.actor)
        session.add(
            ToolCall(
                shop_id=ctx.shop_id,
                conversation_id=ctx.conversation_id,
                message_id=ctx.message_id,
                tool_name=name[:64],
                actor=ctx.actor,
                arguments=args_for_audit,
                status=result.status,
                error_code=result.error_code,
                latency_ms=result.latency_ms,
            )
        )
        await session.flush()
        return result
