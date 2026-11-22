"""Shared fixtures.

Integration tests run against a real PostgreSQL (pgvector) database named in DATABASE_URL /
MIGRATION_DATABASE_URL (``support_test`` in docker compose). The schema is rebuilt from the
migrations and the fictional demo data is seeded once per test session, including the knowledge
base ingestion with the real local embedding model.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("LOG_JSON", "false")
os.environ.setdefault("JWT_SECRET", "test-secret-" + "x" * 40)
# No LLM in the test suite: the agent runs its rule-based planner unless a test injects a scripted model.
os.environ["LLM_PRIMARY_API_KEY"] = ""
os.environ["LLM_PRIMARY_BASE_URL"] = "https://api.openai.com/v1"
os.environ["LLM_FALLBACK_BASE_URL"] = ""
# Provider tuning from a local .env (free-tier presets) must not change what the tests send.
os.environ.update(
    {
        "LLM_REASONING_EFFORT": "",
        "LLM_EXTRA_OUTPUT_TOKENS": "0",
        "LLM_RESPONSE_FORMAT": "auto",
        "LLM_PRIMARY_REQUESTS_PER_MINUTE": "0",
        "LLM_FALLBACK_REQUESTS_PER_MINUTE": "0",
        "LLM_MAX_RETRY_WAIT_SECONDS": "90",
        "JUDGE_MODEL": "",
        "JUDGE_BASE_URL": "",
        "JUDGE_API_KEY": "",
        "JUDGE_REQUESTS_PER_MINUTE": "0",
    }
)
os.environ["LANGFUSE_PUBLIC_KEY"] = ""

import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import create_engine, select, text

from app.config import get_settings

DEMO_ORIGIN = "http://localhost:8080"
DEMO_PASSWORD = "demo-password-2026"


def _reset_database() -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy.engine import make_url

    from app.cli import bootstrap_db

    settings = get_settings()
    # The suite drops the whole schema: never let it touch a database that is not a test database.
    for url in (settings.database_url, settings.migration_database_url):
        if not (make_url(url).database or "").endswith("_test"):
            pytest.exit(f"refusing to run: database '{make_url(url).database}' does not end with '_test'", 2)
    bootstrap_db()
    engine = create_engine(settings.migration_database_url, isolation_level="AUTOCOMMIT")
    role = settings.database_url.split("://", 1)[1].split(":", 1)[0]
    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.execute(text(f'GRANT USAGE ON SCHEMA public TO "{role}"'))
        conn.execute(text("DROP FUNCTION IF EXISTS app_current_shop()"))
    engine.dispose()
    command.upgrade(Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini")), "head")


@pytest_asyncio.fixture(scope="session", autouse=True)
async def database() -> AsyncIterator[None]:
    if os.environ.get("SKIP_DB_TESTS"):
        yield
        return
    _reset_database()
    from app.seed.run import seed_all

    await seed_all(with_knowledge=True)
    yield
    from app.db import dispose_engine

    await dispose_engine()


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    from app.main import app

    transport = httpx.ASGITransport(app=app, client=("203.0.113.7", 50000))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver", headers={"origin": DEMO_ORIGIN}
    ) as http:
        yield http


@pytest.fixture
def settings():
    return get_settings()


@pytest.fixture(autouse=True)
def generous_rate_limits(settings, monkeypatch):
    """Most tests are not about rate limiting; the dedicated tests lower the limits explicitly."""
    monkeypatch.setattr(settings, "rate_limit_chat_per_session", 1000)
    monkeypatch.setattr(settings, "rate_limit_chat_per_ip", 1000)
    monkeypatch.setattr(settings, "rate_limit_login_per_ip", 1000)
    monkeypatch.setattr(settings, "rate_limit_session_create_per_ip", 1000)


async def shop_by_slug(slug: str):
    from app.db import tenant_session
    from app.models import Shop

    async with tenant_session(None) as session:
        return await session.scalar(select(Shop).where(Shop.slug == slug))


@pytest_asyncio.fixture
async def demo_shop():
    return await shop_by_slug("demo-shop")


@pytest_asyncio.fixture
async def casa_shop():
    return await shop_by_slug("casa-lumo")


async def staff_token(client: httpx.AsyncClient, email: str = "admin@brightcart.example.com") -> str:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": DEMO_PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


async def widget_session(client: httpx.AsyncClient, shop: str = "demo-shop", customer: str | None = None) -> dict:
    body: dict[str, Any] = {"shop": shop}
    if customer:
        identity = await client.post("/api/v1/demo/identity", json={"shop": shop, "external_ref": customer})
        assert identity.status_code == 200, identity.text
        body["customer_token"] = identity.json()["customer_token"]
    response = await client.post("/api/v1/widget/sessions", json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def chat(client: httpx.AsyncClient, session: dict, message: str) -> httpx.Response:
    return await client.post(
        "/api/v1/chat/messages",
        json={"message": message},
        headers={"authorization": f"Bearer {session['session_token']}"},
    )


def auth(token: str) -> dict[str, str]:
    return {"authorization": f"Bearer {token}"}


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()
