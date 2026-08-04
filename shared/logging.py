"""Shared runtime logging setup.

Text output is the local default. Set ``RAG_LOG_FORMAT=json`` (or pass
``log_format="json"``) for one-JSON-object-per-line output suitable for log
shipping and indexing in production. ``RAG_LOG_LEVEL`` controls verbosity.

Correlation IDs are threaded through ``correlation_id`` (a contextvar): broker
consumers wrap processing in ``with correlation_id(envelope.correlation_id):``
and both formatters append the active value so a single log stream can be traced
from request acceptance through helper completion.
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

_LOG_RECORD_RESERVED = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "taskName",
        "message",
    }
)

_correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")


def get_correlation_id() -> str:
    """Return the correlation ID active for the current async context."""
    return _correlation_id_var.get()


@contextmanager
def correlation_id(value: str):
    """Run a block with a correlation ID active in the current context.

    Usage (async-safe because contextvars propagate across awaits):

        with correlation_id(envelope.correlation_id):
            await process(envelope)
    """
    token = _correlation_id_var.set(value)
    try:
        yield
    finally:
        _correlation_id_var.reset(token)


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log record.

    ``record`` attributes outside the stdlib reserved set are included as
    top-level fields, so callers can attach structured context via
    ``logger.info(..., extra={"task_id": ...})``. The active correlation ID is
    always included when set.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        correlation_value = get_correlation_id()
        if correlation_value:
            payload["correlation_id"] = correlation_value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack_info"] = self.formatStack(record.stack_info)
        for key, value in record.__dict__.items():
            if key in _LOG_RECORD_RESERVED or key.startswith("_"):
                continue
            payload[key] = value
        return json.dumps(payload, default=str, separators=(",", ":"))


class TextCorrelationFormatter(logging.Formatter):
    """Default text formatter with correlation ID appended when active."""

    def __init__(self, fmt: str = "%(asctime)s %(levelname)s %(name)s %(message)s") -> None:
        super().__init__(fmt=fmt)

    def format(self, record: logging.LogRecord) -> str:
        correlation_value = get_correlation_id()
        if correlation_value:
            message = f"{super().format(record)} correlation_id={correlation_value}"
        else:
            message = super().format(record)
        if record.exc_info:
            message += "\n" + self.formatException(record.exc_info)
        return message


def configure_logging(
    default_level: str = "INFO",
    *,
    log_format: str | None = None,
) -> None:
    """Configure root logging.

    ``log_format`` may be ``"json"`` or ``"text"``; when omitted it is read from
    the ``RAG_LOG_FORMAT`` environment variable (default ``"text"``). Existing
    callers that pass only ``default_level`` keep their current behavior.
    """
    level_name = os.environ.get("RAG_LOG_LEVEL", default_level).strip().upper()
    level = getattr(logging, level_name, logging.INFO)
    fmt = (log_format or os.environ.get("RAG_LOG_FORMAT", "text")).strip().lower()
    if fmt == "json":
        formatter: logging.Formatter = JsonFormatter()
    elif fmt in {"text", "plain"}:
        formatter = TextCorrelationFormatter("%(asctime)s %(levelname)s %(name)s %(message)s%( _correlation_id_suffix)s")
    else:
        raise ValueError(f"unknown RAG_LOG_FORMAT: {fmt!r}")
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers[:] = [handler]
