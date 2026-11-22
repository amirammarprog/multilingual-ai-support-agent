"""Fixed-window rate limiting stored in PostgreSQL, so limits hold across API replicas without
adding Redis. Each hit is one atomic upsert in its own short transaction."""

from __future__ import annotations

import hashlib
import random
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.config import get_settings
from app.db import session_factory
from app.errors import RateLimited

_UPSERT = text(
    "INSERT INTO rate_limit_buckets (key, window_start, count) VALUES (:key, :window, 1) "
    "ON CONFLICT (key, window_start) DO UPDATE SET count = rate_limit_buckets.count + 1 RETURNING count"
)
_CLEANUP = text("DELETE FROM rate_limit_buckets WHERE window_start < :before")


def hash_ip(ip: str | None) -> str:
    """IP addresses are personal data: only a salted hash is used as a key."""
    salt = get_settings().jwt_secret.get_secret_value()[:16]
    return hashlib.sha256(f"{salt}:{ip or 'unknown'}".encode()).hexdigest()[:24]


async def hit(key: str, limit: int, window_seconds: int | None = None) -> int:
    window_seconds = window_seconds or get_settings().rate_limit_window_seconds
    now = datetime.now(UTC)
    window = datetime.fromtimestamp(int(now.timestamp()) // window_seconds * window_seconds, UTC)
    async with session_factory()() as session:
        count = (await session.execute(_UPSERT, {"key": key[:200], "window": window})).scalar_one()
        if random.random() < 0.01:  # noqa: S311 - not security sensitive, just occasional cleanup
            await session.execute(_CLEANUP, {"before": now - timedelta(days=1)})
        await session.commit()
    if count > limit:
        retry = int((window + timedelta(seconds=window_seconds) - now).total_seconds()) + 1
        raise RateLimited(retry_after=max(1, retry))
    return count
