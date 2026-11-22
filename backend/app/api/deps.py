"""FastAPI dependencies: database session, authentication and tenant binding."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import bind_shop, session_factory
from app.errors import Forbidden, Unauthorized
from app.models import Shop, User, UserRole
from app.security.auth import StaffClaims, WidgetClaims, decode_staff_token, decode_widget_token

bearer = HTTPBearer(auto_error=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with session_factory()() as session:
        yield session


Session = Annotated[AsyncSession, Depends(get_session)]
Bearer = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@dataclass
class StaffContext:
    user: User
    shop: Shop
    claims: StaffClaims


async def staff_context(session: Session, credentials: Bearer) -> StaffContext:
    if credentials is None:
        raise Unauthorized("Sign in required.")
    claims = decode_staff_token(credentials.credentials)
    user = await session.get(User, claims.user_id)
    if user is None or not user.is_active or user.shop_id != claims.shop_id:
        raise Unauthorized("Account disabled or not found.")
    shop = await session.get(Shop, claims.shop_id)
    if shop is None:
        raise Unauthorized("Shop not found.")
    await bind_shop(session, shop.id)
    return StaffContext(user=user, shop=shop, claims=claims)


Staff = Annotated[StaffContext, Depends(staff_context)]


def require_role(*roles: UserRole):
    async def check(staff: Staff) -> StaffContext:
        if staff.user.role not in roles:
            raise Forbidden("Your role does not allow this action.")
        return staff

    return Depends(check)


# ---------------------------------------------------------------------------- widget sessions ----
class _OriginCache:
    """Shops' allowed origins, cached for the CORS middleware and widget checks."""

    def __init__(self, ttl: float = 30.0) -> None:
        self.ttl = ttl
        self._loaded = 0.0
        self._by_shop: dict[str, set[str]] = {}

    async def refresh(self, force: bool = False) -> None:
        if not force and time.monotonic() - self._loaded < self.ttl:
            return
        async with session_factory()() as session:
            rows = (await session.execute(select(Shop.id, Shop.allowed_origins))).all()
        self._by_shop = {str(shop_id): {o.rstrip("/") for o in origins or []} for shop_id, origins in rows}
        self._loaded = time.monotonic()

    def all(self) -> set[str]:
        return set().union(*self._by_shop.values()) if self._by_shop else set()

    def allowed(self, shop_id: str, origin: str | None) -> bool:
        # Server-to-server calls (no Origin header) are allowed; browsers always send Origin on CORS requests.
        return origin is None or origin.rstrip("/") in self._by_shop.get(shop_id, set())


origin_cache = _OriginCache()


@dataclass
class WidgetContext:
    claims: WidgetClaims
    shop: Shop


async def widget_context(request: Request, session: Session, credentials: Bearer) -> WidgetContext:
    if credentials is None:
        raise Unauthorized("Chat session required.")
    claims = decode_widget_token(credentials.credentials)
    shop = await session.get(Shop, claims.shop_id)
    if shop is None:
        raise Unauthorized("Shop not found.")
    await origin_cache.refresh()
    if not origin_cache.allowed(str(shop.id), request.headers.get("origin")):
        raise Forbidden("This website is not allowed to use this shop's assistant.")
    await bind_shop(session, shop.id)
    return WidgetContext(claims=claims, shop=shop)


Widget = Annotated[WidgetContext, Depends(widget_context)]
