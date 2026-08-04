"""Optional OpenTelemetry tracing for the broker message path.

Tracing is opt-in: when ``RAG_OTEL_ENDPOINT`` (an OTLP/gRPC endpoint) is set and
the ``qdrant-rag-server[tracing]`` extras are installed, a tracer provider is
configured once per process; otherwise every helper degrades to a no-op so the
runtime is unaffected. Service names come from the worker label, and spans carry
the broker message ``correlation_id``/``task_id`` so logs, metrics, and traces
share one correlation key.
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


def setup_tracing(service_name: str, *, values: dict[str, str] | None = None) -> Any:
    """Configure OTel for the process (idempotent) and return a tracer.

    Returns a no-op tracer when disabled or when the extras are missing.
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
    provider = TracerProvider(
        resource=Resource.create({"service.name": service_name})
    )
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer(service_name)
    logger.info("opentelemetry tracing enabled endpoint=%s service=%s", endpoint, service_name)
    return _tracer


@contextmanager
def optional_span(tracer: Any, name: str, **attributes: Any) -> Iterator[None]:
    """Yield a started current span when ``tracer`` is real, else a no-op.

    Attributes are set on the span when provided (values are coerced to str).
    """
    if tracer is None:
        yield
        return
    with tracer.start_as_current_span(name) as span:
        for key, value in attributes.items():
            span.set_attribute(key, str(value))
        yield


def _noop_tracer() -> Any:
    return None


__all__ = ["optional_span", "setup_tracing"]
