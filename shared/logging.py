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

_SENSITIVE_FRAGMENTS = (
    "password",
    "passwd",
    "api_key",
    "apikey",
    "token",
    "secret",
    "credential",
    "authorization",
    "private_key",
    "master_key",
)

# Fields the formatter sets itself; extra= must not overwrite them.
_CORE_FIELDS = frozenset(
    {"ts", "level", "logger", "msg", "service", "environment", "version",
     "correlation_id", "trace_id", "exc_info"}
)

_correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")

# Service identity stamped onto every JSON log record. Populated by
# ``configure_logging`` from explicit kwargs or the RAG_* env vars.
_service_context: dict[str, str] = {}


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


def _otel_trace_id() -> str:
    """Return the active OTel span's trace ID, or empty when tracing is off."""
    try:
        from opentelemetry import trace
    except ImportError:
        return ""
    span = trace.get_current_span()
    context = span.get_span_context()
    if context.is_valid and context.trace_id != 0:
        return format(context.trace_id, "032x")
    return ""


def _redact_value(key: str, value: Any) -> Any:
    lowered = key.lower()
    if any(fragment in lowered for fragment in _SENSITIVE_FRAGMENTS):
        return "***"
    if isinstance(value, dict):
        return {k: _redact_value(k, v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_value(key, v) for v in value]
    if isinstance(value, str):
        lowered_value = value.lower()
        for fragment in _SENSITIVE_FRAGMENTS:
            if fragment in lowered_value and len(value) >= 8:
                return "***"
    return value


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log record.

    ``record`` attributes outside the stdlib reserved set are included as
    top-level fields, so callers can attach structured context via
    ``logger.info(..., extra={"task_id": ...})``. The active correlation ID is
    always included when set, and service/environment/version are stamped from
    ``configure_logging`` context when provided.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        service = _service_context.get("service")
        if service:
            payload["service"] = service
        environment = _service_context.get("environment")
        if environment:
            payload["environment"] = environment
        version = _service_context.get("version")
        if version:
            payload["version"] = version
        correlation_value = get_correlation_id()
        if correlation_value:
            payload["correlation_id"] = correlation_value
        trace_id = _otel_trace_id()
        if trace_id:
            payload["trace_id"] = trace_id
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack_info"] = self.formatStack(record.stack_info)
        for key, value in record.__dict__.items():
            if key in _LOG_RECORD_RESERVED or key in _CORE_FIELDS or key.startswith("_"):
                continue
            payload[key] = _redact_value(key, value)
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
    service_name: str | None = None,
    service_version: str | None = None,
    environment: str | None = None,
) -> None:
    """Configure root logging.

    ``log_format`` may be ``"json"`` or ``"text"``; when omitted it is read from
    the ``RAG_LOG_FORMAT`` environment variable (default ``"text"``). Existing
    callers that pass only ``default_level`` keep their current behavior.

    ``service_name``/``service_version``/``environment`` stamp the fleet-standard
    ``service``/``version``/``environment`` fields onto JSON records; each
    defaults from ``RAG_SERVICE_NAME``/``RAG_VERSION``/``RAG_ENVIRONMENT``.
    """
    _service_context.update(
        service=service_name if service_name is not None else os.environ.get("RAG_SERVICE_NAME", ""),
        version=service_version
        if service_version is not None
        else os.environ.get("RAG_VERSION", ""),
        environment=environment
        if environment is not None
        else os.environ.get("RAG_ENVIRONMENT", ""),
    )
    level_name = os.environ.get("RAG_LOG_LEVEL", default_level).strip().upper()
    level = getattr(logging, level_name, logging.INFO)
    fmt = (log_format or os.environ.get("RAG_LOG_FORMAT", "text")).strip().lower()
    if fmt == "json":
        formatter: logging.Formatter = JsonFormatter()
    elif fmt in {"text", "plain"}:
        formatter = TextCorrelationFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    else:
        raise ValueError(f"unknown RAG_LOG_FORMAT: {fmt!r}")
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers[:] = [handler]
