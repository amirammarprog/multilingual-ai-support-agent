"""The shop tools exposed over the Model Context Protocol (streamable HTTP at ``/mcp``).

Any MCP client can list and call the same tools the agent uses. Authentication is a bearer token:
a staff token (admin console) or a widget session token. The token decides the shop, the identity
and the scopes; the same registry performs the same permission checks as for the built-in agent.
"""

from __future__ import annotations

import contextvars
import json
from typing import Any

import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.types import Receive, Scope, Send

from app.db import tenant_session
from app.errors import Unauthorized
from app.models import Conversation
from app.security.auth import decode_staff_token, decode_widget_token
from app.tools.business import registry
from app.tools.registry import STAFF_SCOPES, WIDGET_SCOPES, ToolContext

_context: contextvars.ContextVar[ToolContext | None] = contextvars.ContextVar("mcp_tool_context", default=None)


async def _list_tools(_ctx: Any, _params: Any) -> types.ListToolsResult:
    tool_ctx = _context.get()
    scopes = tool_ctx.scopes if tool_ctx else frozenset()
    return types.ListToolsResult(
        tools=[
            types.Tool(
                name=spec.name,
                description=spec.description,
                inputSchema=spec.json_schema(),
                annotations=types.ToolAnnotations(readOnlyHint=spec.read_only),
            )
            for spec in registry.available(scopes)
        ]
    )


async def _call_tool(_ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
    tool_ctx = _context.get()
    if tool_ctx is None:
        return types.CallToolResult(content=[types.TextContent(type="text", text="unauthenticated")], isError=True)
    async with tenant_session(tool_ctx.shop_id) as session:
        if tool_ctx.conversation_id:
            conversation = await session.get(Conversation, tool_ctx.conversation_id)
            if conversation is not None:
                tool_ctx.verified_orders = set(conversation.verified_orders or [])
                tool_ctx.failed_verifications = conversation.failed_verifications
        result = await registry.execute(session, params.name, dict(params.arguments or {}), tool_ctx)
        await session.commit()
    payload = result.for_model()
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, default=str))],
        structuredContent=payload,
        isError=not result.ok,
    )


server: Server[Any] = Server("shop-support-tools", version="1.0.0", on_list_tools=_list_tools, on_call_tool=_call_tool)


def create_session_manager() -> StreamableHTTPSessionManager:
    # Stateless JSON responses: every request is authenticated on its own, no server-side MCP session.
    return StreamableHTTPSessionManager(app=server, stateless=True, json_response=True)


session_manager = create_session_manager()


def context_from_token(token: str) -> ToolContext:
    """Staff tokens get staff scopes in their shop; widget tokens act as that chat visitor."""
    try:
        staff = decode_staff_token(token)
        return ToolContext(shop_id=staff.shop_id, actor="mcp", scopes=STAFF_SCOPES)
    except Unauthorized:
        widget = decode_widget_token(token)
        return ToolContext(
            shop_id=widget.shop_id,
            actor="mcp",
            scopes=WIDGET_SCOPES,
            customer_id=widget.customer_id,
            conversation_id=widget.conversation_id,
        )


async def mcp_asgi(scope: Scope, receive: Receive, send: Send) -> None:
    headers = dict(scope.get("headers") or [])
    auth = headers.get(b"authorization", b"").decode()
    if not auth.lower().startswith("bearer "):
        await _reject(send, "missing bearer token")
        return
    try:
        tool_ctx = context_from_token(auth[7:].strip())
    except Unauthorized:
        await _reject(send, "invalid token")
        return
    token = _context.set(tool_ctx)
    try:
        await session_manager.handle_request(scope, receive, send)
    finally:
        _context.reset(token)


async def _reject(send: Send, message: str) -> None:
    body = json.dumps({"error": {"code": "unauthorized", "message": message}}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [(b"content-type", b"application/json"), (b"www-authenticate", b"Bearer")],
        }
    )
    await send({"type": "http.response.body", "body": body})
