"""Langfuse tracing (latency, tokens, cost per step). Disabled, at zero cost, when no keys are set.

Inputs and outputs pass through the same redaction as the logs before they leave the process.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from app.config import get_settings
from app.logs import get_logger
from app.security.redaction import redact

log = get_logger("observability")


class _NoopObservation:
    id = None
    trace_id = None

    def update(self, **_: Any) -> _NoopObservation:
        return self


class Tracer:
    def __init__(self) -> None:
        self._client: Any = None
        self._initialised = False

    @property
    def client(self) -> Any:
        if not self._initialised:
            self._initialised = True
            settings = get_settings()
            secret = settings.langfuse_secret_key.get_secret_value()
            if settings.langfuse_public_key and secret:
                try:
                    from langfuse import Langfuse

                    self._client = Langfuse(
                        public_key=settings.langfuse_public_key,
                        secret_key=secret,
                        host=settings.langfuse_host,
                        environment=settings.app_env,
                        mask=lambda data, **_: redact(data),
                    )
                    log.info("langfuse_enabled", host=settings.langfuse_host)
                except Exception:
                    log.exception("langfuse_init_failed")
        return self._client

    @property
    def enabled(self) -> bool:
        return self.client is not None

    @contextmanager
    def span(self, name: str, *, as_type: str = "span", **fields: Any) -> Iterator[Any]:
        if not self.enabled:
            yield _NoopObservation()
            return
        try:
            cm = self.client.start_as_current_observation(name=name, as_type=as_type, **fields)
            obs = cm.__enter__()
        except Exception:
            log.exception("langfuse_span_failed")
            yield _NoopObservation()
            return
        try:
            yield obs
        finally:
            cm.__exit__(None, None, None)

    @contextmanager
    def generation(self, *, name: str, model: str, input: Any, metadata: dict[str, Any]) -> Iterator[Any]:
        with self.span(name, as_type="generation", model=model, input=input, metadata=metadata) as gen:
            yield gen

    def current_trace_id(self) -> str | None:
        if not self.enabled:
            return None
        try:
            return self.client.get_current_trace_id()
        except Exception:
            return None

    def flush(self) -> None:
        if self.enabled:
            try:
                self.client.flush()
            except Exception:
                log.warning("langfuse_flush_failed")


tracer = Tracer()
