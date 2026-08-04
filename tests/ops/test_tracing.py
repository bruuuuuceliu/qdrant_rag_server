"""Optional OpenTelemetry tracing helper tests."""

from __future__ import annotations

from shared.ops.tracing import optional_span, setup_tracing


def test_setup_tracing_disabled_without_endpoint() -> None:
    tracer = setup_tracing("test-service", values={})
    assert tracer is None


def test_setup_tracing_without_extras_is_noop(caplog: object) -> None:
    # Endpoint set but opentelemetry extras are not installed: must not raise.
    tracer = setup_tracing("test-service", values={"RAG_OTEL_ENDPOINT": "http://otel:4317"})
    assert tracer is None


def test_optional_span_noop_without_tracer() -> None:
    with optional_span(None, "test.span", task_id="task-1"):
        pass  # must not raise


def test_setup_tracing_is_idempotent() -> None:
    first = setup_tracing("service-a", values={})
    second = setup_tracing("service-b", values={"RAG_OTEL_ENDPOINT": "http://otel:4317"})
    assert first is None
    assert second is None
