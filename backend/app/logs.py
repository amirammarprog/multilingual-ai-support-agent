"""Structured logging. Every event passes through the redaction processor."""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from app.security.redaction import redact


def _redact_processor(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    return {k: (v if k in {"timestamp", "level", "logger"} else redact(v)) for k, v in event_dict.items()}


def configure_logging(level: str = "INFO", json_output: bool = True) -> None:
    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _redact_processor,
    ]
    renderer: Any = structlog.processors.JSONRenderer() if json_output else structlog.dev.ConsoleRenderer()
    structlog.configure(
        processors=[*shared, structlog.processors.format_exc_info, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelNamesMapping()[level.upper()]),
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        cache_logger_on_first_use=True,
    )
    # Keep third-party loggers quiet and route them to stdout as plain lines.
    logging.basicConfig(level=level.upper(), stream=sys.stdout, format="%(levelname)s %(name)s %(message)s")
    for noisy in ("httpx", "httpcore", "urllib3", "huggingface_hub", "faster_whisper", "opentelemetry"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str = "app") -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
