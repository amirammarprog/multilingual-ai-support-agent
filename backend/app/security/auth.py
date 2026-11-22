"""Passwords and tokens.

Three kinds of JWT exist and are never interchangeable (each has its own ``typ`` and audience):

* staff      - admin console users; carries shop and role.
* widget     - one chat session in the embeddable widget; carries shop, conversation and, when
               the shop vouched for the visitor, the customer id.
* identity   - signed by the *shop's own backend* with its widget secret to say "this visitor is
               customer X". Exchanged once for a widget session; never accepted anywhere else.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
from pwdlib import PasswordHash

from app.config import get_settings
from app.errors import Unauthorized

_hasher = PasswordHash.recommended()  # argon2id
_ALGORITHM = "HS256"

# A real hash of a random value, verified on unknown e-mails so login timing does not reveal accounts.
_DUMMY_HASH = _hasher.hash(uuid.uuid4().hex)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _hasher.verify(password, password_hash or _DUMMY_HASH) and password_hash is not None
    except Exception:
        return False


TokenType = Literal["staff", "widget"]


@dataclass(frozen=True)
class StaffClaims:
    user_id: uuid.UUID
    shop_id: uuid.UUID
    role: str


@dataclass(frozen=True)
class WidgetClaims:
    shop_id: uuid.UUID
    conversation_id: uuid.UUID
    customer_id: uuid.UUID | None
    session_id: str


def _encode(payload: dict[str, Any], ttl: timedelta) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        **payload,
        "iss": settings.jwt_issuer,
        "iat": now,
        "nbf": now,
        "exp": now + ttl,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm=_ALGORITHM)


def _decode(token: str, typ: TokenType) -> dict[str, Any]:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[_ALGORITHM],
            audience=f"support-agent:{typ}",
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "iat", "sub", "aud", "typ"]},
        )
    except jwt.PyJWTError as exc:
        raise Unauthorized("Invalid or expired token.") from exc
    if payload.get("typ") != typ:
        raise Unauthorized("Invalid token type.")
    return payload


def issue_staff_token(user_id: uuid.UUID, shop_id: uuid.UUID, role: str) -> str:
    ttl = timedelta(minutes=get_settings().staff_token_ttl_minutes)
    return _encode(
        {
            "sub": str(user_id),
            "shop": str(shop_id),
            "role": role,
            "typ": "staff",
            "aud": "support-agent:staff",
        },
        ttl,
    )


def decode_staff_token(token: str) -> StaffClaims:
    p = _decode(token, "staff")
    return StaffClaims(uuid.UUID(p["sub"]), uuid.UUID(p["shop"]), p["role"])


def issue_widget_token(shop_id: uuid.UUID, conversation_id: uuid.UUID, customer_id: uuid.UUID | None) -> str:
    ttl = timedelta(minutes=get_settings().widget_session_ttl_minutes)
    return _encode(
        {
            "sub": str(conversation_id),
            "shop": str(shop_id),
            "cus": str(customer_id) if customer_id else None,
            "typ": "widget",
            "aud": "support-agent:widget",
        },
        ttl,
    )


def decode_widget_token(token: str) -> WidgetClaims:
    p = _decode(token, "widget")
    return WidgetClaims(
        shop_id=uuid.UUID(p["shop"]),
        conversation_id=uuid.UUID(p["sub"]),
        customer_id=uuid.UUID(p["cus"]) if p.get("cus") else None,
        session_id=p["jti"],
    )


# ---------------------------------------------------------------- shop-signed customer identity ----
def sign_customer_identity(widget_secret: str, shop_slug: str, external_ref: str, ttl_minutes: int = 10) -> str:
    """What a shop's backend does to vouch for a signed-in customer (see README, "Identity")."""
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": external_ref,
            "shop": shop_slug,
            "iat": now,
            "exp": now + timedelta(minutes=ttl_minutes),
            "aud": "support-agent:identity",
        },
        widget_secret,
        algorithm=_ALGORITHM,
    )


def verify_customer_identity(token: str, widget_secret: str, shop_slug: str) -> str:
    try:
        payload = jwt.decode(
            token,
            widget_secret,
            algorithms=[_ALGORITHM],
            audience="support-agent:identity",
            options={"require": ["exp", "iat", "sub", "aud"]},
        )
    except jwt.PyJWTError as exc:
        raise Unauthorized("Invalid customer identity token.") from exc
    if payload.get("shop") != shop_slug:
        raise Unauthorized("Customer identity token was issued for another shop.")
    issued = datetime.fromtimestamp(payload["iat"], UTC)
    if datetime.now(UTC) - issued > timedelta(hours=1):
        raise Unauthorized("Customer identity token is too old.")
    return str(payload["sub"])
