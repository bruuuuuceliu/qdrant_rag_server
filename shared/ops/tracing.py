"""Optional OpenTelemetry tracing for the broker message path.

Tracing is opt-in: when ``RAG_OTEL_ENDPOINT`` (an OTLP/gRPC endpoint) is set and
the ``qdrant-rag-server[tracing]`` extras are installed, a tracer provider is
configured once per process; otherwise every helper degrades to a no-op so the
runtime is unaffected. Service names come from the worker label, and spans carry
the broker message ``correlation_id``/``task_id`` so logs, metrics, and traces
share one correlation key. Cross-service traces are joined by threading the
W3C ``traceparent`` through broker envelope headers and payload context.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)

_tracer: Any = None
_configured: bool = False


def setup_tracing(
    service_name: str,
    *,
    values: dict[str, str] | None = None,
    service_version: str | None = None,
    environment: str | None = None,
) -> Any:
    """Configure OTel for the process (idempotent) and return a tracer.

    ``service_version``/``environment`` default from ``RAG_VERSION``/
    ``RAG_ENVIRONMENT``. Returns a no-op tracer when disabled or when the
    extras are missing.
    """
    global _tracer, _configured
    if _configured:
        return _tracer or _noop_tracer()
    _configured = True
    values = os.environ if values is None else values
    endpoint = (values.get("RAG_OTEL_ENDPOINT") or "").strip()
    if not endpoint:
        return _noop_tracer()
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:  # pragma: no cover - optional extras
        logger.warning(
            "RAG_OTEL_ENDPOINT is set but opentelemetry extras are not installed; "
            "install with: pip install 'qdrant-rag-server[tracing]'"
        )
        return _noop_tracer()
    resource_attributes: dict[str, str] = {"service.name": service_name}
    version = (
        service_version
        if service_version is not None
        else (values.get("RAG_VERSION") or "").strip()
    )
    if version:
        resource_attributes["service.version"] = version
    env_name = (
        environment
        if environment is not None
        else (values.get("RAG_ENVIRONMENT") or "").strip()
    )
    if env_name:
        resource_attributes["deployment.environment"] = env_name
    provider = TracerProvider(
        resource=Resource.create(resource_attributes)
    )
    # Bare host:port endpoints are the convention in this repo's compose;
    # treat them as plaintext OTLP/gRPC (the collector's listener has no TLS).
    insecure = not endpoint.startswith("https://")
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=insecure))
    )
    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer(service_name)
    logger.info("opentelemetry tracing enabled endpoint=%s service=%s", endpoint, service_name)
    return _tracer


def _stamp_attributes(span: Any, attributes: dict[str, Any]) -> None:
    for key, value in attributes.items():
        span.set_attribute(key, str(value))


def _stamp_trace_id(span: Any) -> None:
    span_context = span.get_span_context()
    if span_context.is_valid and span_context.trace_id != 0:
        span.set_attribute("trace_id", format(span_context.trace_id, "032x"))


@contextmanager
def optional_span(tracer: Any, name: str, **attributes: Any) -> Iterator[None]:
    """Yield a started current span when ``tracer`` is real, else a no-op.

    Attributes are set on the span when provided (values are coerced to str).
    The span's ``trace_id`` is always stamped so logs and traces share the
    correlation key.
    """
    if tracer is None:
        yield
        return
    with tracer.start_as_current_span(name) as span:
        _stamp_attributes(span, attributes)
        _stamp_trace_id(span)
        yield


def _context_from_traceparent(traceparent: str | None) -> Any:
    """Return an OTel context for a W3C traceparent, or None when invalid."""
    try:
        from opentelemetry import trace
        from opentelemetry.trace.propagation.tracecontext import (
            TraceContextTextMapPropagator,
        )
    except ImportError:  # pragma: no cover - optional extras
        return None
    try:
        context = TraceContextTextMapPropagator().extract({"traceparent": traceparent})
        span = trace.get_current_span(context)
        if not span.get_span_context().is_valid:
            return None
        return context
    except Exception:  # pragma: no cover - malformed traceparent
        return None


@contextmanager
def resume_span(
    tracer: Any,
    traceparent: str | None,
    name: str,
    **attributes: Any,
) -> Iterator[Any]:
    """Yield a span resumed from a W3C traceparent, else a no-op.

    When ``traceparent`` carries a valid remote context the new span is its
    child, joining the cross-service trace; otherwise a fresh span is started.
    Attributes and ``trace_id`` are stamped like ``optional_span``.
    """
    if tracer is None:
        yield
        return
    with tracer.start_as_current_span(
        name, context=_context_from_traceparent(traceparent)
    ) as span:
        _stamp_attributes(span, attributes)
        _stamp_trace_id(span)
        yield span


def traceparent_from_envelope(envelope: Any) -> str | None:
    """Return the W3C traceparent threaded through an envelope, if any."""
    headers = getattr(envelope, "headers", None)
    if isinstance(headers, dict):
        value = str(headers.get("traceparent") or "").strip()
        if value:
            return value
    payload = getattr(envelope, "payload", None)
    if isinstance(payload, dict):
        context = payload.get("context")
        if isinstance(context, dict):
            value = str(context.get("traceparent") or "").strip()
            if value:
                return value
    return None


def active_traceparent() -> str:
    """Return the W3C traceparent of the active span, or ``""`` when off."""
    try:
        from opentelemetry import trace
    except ImportError:  # pragma: no cover - optional extras
        return ""
    span = trace.get_current_span()
    span_context = span.get_span_context()
    if not span_context.is_valid or span_context.trace_id == 0:
        return ""
    flags = span_context.trace_flags
    sampled = "01" if flags.sampled else "00"
    return f"00-{span_context.trace_id:032x}-{span_context.span_id:016x}-{sampled}"


def _noop_tracer() -> Any:
    return None


__all__ = [
    "active_traceparent",
    "optional_span",
    "resume_span",
    "setup_tracing",
    "traceparent_from_envelope",
]
