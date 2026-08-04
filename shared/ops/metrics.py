"""Prometheus metrics namespace shared by RAG services.

All services import this single module, so the metric objects are process-level
singletons registered once on the default ``REGISTRY``. The ``service`` label
on task/consume metrics disambiguates scrapes that aggregate many worker
processes. ``prometheus-client`` is a base dependency; if it is ever missing the
module degrades to no-op metric objects so service startup does not fail.

Only generic, transport-neutral metrics live here. Service-specific business
counters belong in the owning service (see ``retrieval_service.health``).
"""

from __future__ import annotations

from typing import Any

try:  # pragma: no cover - exercised only when prometheus-client is absent
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        REGISTRY,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
    )

    _ENABLED = True
except ImportError:  # pragma: no cover
    _ENABLED = False
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"

    class _NoopMetric:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._labels: dict[str, str] = {}

        def labels(self, **kwargs: Any) -> _NoopMetric:
            self._labels.update(kwargs)
            return self

        def inc(self, amount: float = 1) -> None:
            pass

        def dec(self, amount: float = 1) -> None:
            pass

        def set(self, value: float) -> None:
            pass

        def observe(self, amount: float) -> None:
            pass

    def _noop_factory() -> type[_NoopMetric]:
        return _NoopMetric

    Counter = _noop_factory()  # type: ignore[misc]
    Gauge = _noop_factory()  # type: ignore[misc]
    Histogram = _noop_factory()  # type: ignore[misc]

    def generate_latest() -> bytes:
        return b""

    def _registry() -> Any:
        return None

    REGISTRY = None  # type: ignore[assignment]


# ---- Lifecycle / task throughput --------------------------------------------

tasks_accepted = Counter(
    "rag_tasks_accepted_total",
    "Tasks accepted into the system through the manager/intake edge.",
    ("service",),
)
tasks_completed = Counter(
    "rag_tasks_completed_total",
    "Tasks that reached a completed terminal state.",
    ("service",),
)
tasks_failed = Counter(
    "rag_tasks_failed_total",
    "Tasks that reached a failed terminal state.",
    ("service",),
)

# ---- Broker transport --------------------------------------------------------

broker_messages_produced = Counter(
    "rag_broker_messages_produced_total",
    "Messages published to the broker.",
    ("topic",),
)
broker_messages_consumed = Counter(
    "rag_broker_messages_consumed_total",
    "Messages consumed from the broker.",
    ("topic", "group"),
)
broker_consume_latency = Histogram(
    "rag_broker_consume_seconds",
    "Time spent processing one consumed message, from receipt to commit.",
    ("group",),
)

# ---- Helper / retrieval work -------------------------------------------------

helper_command_latency = Histogram(
    "rag_helper_command_seconds",
    "End-to-end helper command processing time observed by task service.",
    ("helper",),
)

# ---- Ops HTTP surface --------------------------------------------------------

http_requests = Counter(
    "rag_http_requests_total",
    "Requests served by the ops HTTP surface.",
    ("method", "path", "status"),
)
http_requests_in_flight = Gauge(
    "rag_http_requests_in_flight",
    "Ops HTTP requests currently being served.",
)
service_ready = Gauge(
    "rag_ops_ready",
    "1 when the service reported ready for traffic, 0 otherwise.",
    ("service",),
)


def render() -> bytes:
    """Return the current Prometheus text exposition for all collectors."""
    return generate_latest()


__all__ = [
    "CONTENT_TYPE_LATEST",
    "broker_consume_latency",
    "broker_messages_consumed",
    "broker_messages_produced",
    "helper_command_latency",
    "http_requests",
    "http_requests_in_flight",
    "render",
    "service_ready",
    "tasks_accepted",
    "tasks_completed",
    "tasks_failed",
]
