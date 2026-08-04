"""Shared Prometheus metrics namespace tests."""

from __future__ import annotations

from shared.ops import metrics


def test_render_returns_prometheus_text() -> None:
    body = metrics.render()
    assert isinstance(body, bytes)
    assert b"rag_tasks_accepted_total" in body


def test_counters_increment_and_render() -> None:
    before = metrics.render()
    metrics.tasks_accepted.labels(service="test-service").inc()
    metrics.broker_messages_produced.labels(topic="test.topic").inc()
    metrics.broker_messages_consumed.labels(topic="test.topic", group="test-group").inc()
    after = metrics.render()
    # render() is cumulative across the whole test process, so assert on the
    # labels we just emitted rather than exact deltas.
    assert b"service=\"test-service\"" in after
    assert b"topic=\"test.topic\"" in after
    assert b"group=\"test-group\"" in after
    assert len(after) >= len(before)


def test_service_ready_gauge() -> None:
    metrics.service_ready.labels(service="probe").set(1)
    body = metrics.render()
    assert b"rag_ops_ready" in body
