"""Database engine and sessions.

Tenant isolation is enforced twice:
1. Every repository query filters on ``shop_id``.
2. PostgreSQL row-level security (see the initial migration) hides rows of other shops from the
   application role. The current shop is passed to PostgreSQL with ``set_config('app.shop_id', ...)``
   at the start of every transaction, so a forgotten filter returns nothing instead of leaking data.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from app.config import get_settings

_engine: AsyncEngine | None = None
_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine, _factory
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            pool_size=settings.db_pool_size,
            max_overflow=5,
            pool_pre_ping=True,
        )
        _factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def session_factory() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _factory is not None
    return _factory


async def dispose_engine() -> None:
    global _engine, _factory
    if _engine is not None:
        await _engine.dispose()
    _engine, _factory = None, None


@event.listens_for(Session, "after_begin")
def _apply_tenant(session: Session, _transaction: Any, connection: Any) -> None:
    """Pass the session's shop to PostgreSQL for row-level security (transaction-local)."""
    shop_id = session.info.get("shop_id")
    connection.exec_driver_sql("SELECT set_config('app.shop_id', %s, true)", (str(shop_id) if shop_id else "",))


@asynccontextmanager
async def tenant_session(shop_id: uuid.UUID | None) -> AsyncIterator[AsyncSession]:
    """A session bound to one shop. ``None`` means no tenant: RLS-protected tables look empty."""
    async with session_factory()() as session:
        session.info["shop_id"] = shop_id
        yield session


async def bind_shop(session: AsyncSession, shop_id: uuid.UUID) -> None:
    """Bind an existing session to a shop, including the transaction already in progress."""
    session.info["shop_id"] = shop_id
    if session.in_transaction():
        await session.execute(text("SELECT set_config('app.shop_id', :v, true)"), {"v": str(shop_id)})
