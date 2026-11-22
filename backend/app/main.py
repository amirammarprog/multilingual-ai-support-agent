"""FastAPI application: middleware, routers, MCP endpoint and lifecycle."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from sqlalchemy import select, text
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.routing import Mount

from app.api import routes_admin, routes_chat, routes_evals
from app.api.deps import origin_cache
from app.config import get_settings
from app.db import dispose_engine, session_factory
from app.errors import install_error_handlers
from app.llm.client import get_llm
from app.logs import configure_logging, get_logger
from app.models import Shop
from app.observability import tracer
from app.tools import mcp_server

log = get_logger("main")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("x-request-id", "")[:64] or uuid.uuid4().hex
        request.state.request_id = request_id
        structlog.contextvars.bind_contextvars(request_id=request_id, path=request.url.path)
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.clear_contextvars()
        response.headers["x-request-id"] = request_id
        response.headers["x-content-type-options"] = "nosniff"
        response.headers["referrer-policy"] = "strict-origin-when-cross-origin"
        response.headers["x-frame-options"] = "DENY"
        return response


class DynamicCORSMiddleware(BaseHTTPMiddleware):
    """CORS for the configured origins plus every shop's allowed origins (the widget runs on shop sites).
    No cookies are used (bearer tokens only), so credentials are never allowed."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        origin = request.headers.get("origin")
        allowed = False
        if origin:
            await origin_cache.refresh()
            allowed = origin.rstrip("/") in origin_cache.all() | set(get_settings().cors_origins)
        if request.method == "OPTIONS" and request.headers.get("access-control-request-method"):
            response = Response(status_code=204 if allowed else 403)
        else:
            response = await call_next(request)
        if allowed and origin:
            response.headers["access-control-allow-origin"] = origin
            response.headers["vary"] = "Origin"
            response.headers["access-control-allow-methods"] = "GET, POST, DELETE, OPTIONS"
            response.headers["access-control-allow-headers"] = (
                "authorization, content-type, x-language-hint, x-request-id"
            )
            response.headers["access-control-max-age"] = "600"
        return response


async def _warm_models() -> None:
    settings = get_settings()
    try:
        from app.rag.embeddings import LocalEmbedder, get_embedder
        from app.rag.reranker import CrossEncoderReranker, get_reranker

        embedder, reranker = get_embedder(), get_reranker()
        if isinstance(embedder, LocalEmbedder):
            await asyncio.to_thread(embedder.warm_up)
        if isinstance(reranker, CrossEncoderReranker):
            await asyncio.to_thread(reranker.warm_up)
        log.info("models_ready", embedder=settings.embedding_model, reranker=settings.reranker_model)
    except Exception:
        log.exception("model_warm_up_failed")


async def _resume_ingestion() -> None:
    from app.rag.ingestion import resume_pending

    try:
        async with session_factory()() as session:
            shop_ids = list((await session.scalars(select(Shop.id))).all())
        resumed = await resume_pending(shop_ids)
        if resumed:
            log.info("ingestion_resumed", documents=resumed)
    except Exception:
        log.exception("ingestion_resume_failed")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    log.info("starting", env=settings.app_env, llm_providers=get_llm().describe(), langfuse=tracer.enabled)
    background = []
    if settings.app_env != "test":
        background = [asyncio.create_task(_warm_models()), asyncio.create_task(_resume_ingestion())]
    async with mcp_server.session_manager.run():
        yield
    for task in background:
        task.cancel()
    tracer.flush()
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Multilingual AI Support Agent",
        version="1.0.0",
        description="Customer-support agent for e-commerce shops (Arabic, Tunisian Arabic, French, English). "
        "Grounded answers with citations, permission-checked tools, human hand-off.",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
    )
    install_error_handlers(app)
    app.add_middleware(DynamicCORSMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.include_router(routes_chat.router)
    app.include_router(routes_chat.demo)
    app.include_router(routes_admin.router)
    app.include_router(routes_evals.router)
    app.router.routes.append(Mount("/mcp", app=mcp_server.mcp_asgi))

    @app.get("/health/live", tags=["health"])
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", tags=["health"])
    async def ready() -> dict[str, object]:
        async with session_factory()() as session:
            await session.execute(text("SELECT 1"))
        llm = get_llm()
        return {
            "status": "ok",
            "database": "ok",
            "llm_providers": [p["provider"] for p in llm.describe()],
            "langfuse": tracer.enabled,
            "stt": settings.stt_provider,
            "tts": settings.tts_provider,
        }

    return app


app = create_app()
