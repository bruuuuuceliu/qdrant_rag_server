"""Broker topic bootstrap tests."""

from __future__ import annotations

import pytest

from broker_service import (
    BrokerSettings,
    BrokerLagTarget,
    bootstrap_topics,
    broker_health,
    required_topics,
)
from shared.contracts import TOPICS


class FakeAdmin:
    def __init__(self) -> None:
        self.settings = BrokerSettings(topic_partitions=4)
        self.calls: list[tuple[tuple[str, ...], int]] = []

    async def ensure_topics(self, topics: tuple[str, ...], *, partitions: int = 1) -> None:
        self.calls.append((topics, partitions))

    async def health(self, *, required_topics: tuple[str, ...]):
        self.health_topics = required_topics
        return _Health()

    async def consumer_group_lag(self, group_id: str, topic: str) -> tuple[int, ...]:
        self.lag_call = (group_id, topic)
        return (2, 3)


class _Health:
    def to_payload(self) -> dict[str, object]:
        return {"ok": True, "topics": ["task.intake"]}


def test_required_topics_uses_canonical_topic_set() -> None:
    topics = required_topics()

    assert TOPICS.task_requests in topics
    assert TOPICS.task_events in topics
    assert TOPICS.task_intake in topics
    assert TOPICS.project_plan_requests in topics
    assert TOPICS.project_plan_results in topics
    assert TOPICS.helper_retrieval_results in topics
    assert len(topics) == len(set(topics))


@pytest.mark.asyncio
async def test_bootstrap_topics_uses_configured_partitions() -> None:
    admin = FakeAdmin()

    await bootstrap_topics(admin)

    assert admin.calls == [(required_topics(), 4)]


def test_broker_settings_loads_topic_partitions() -> None:
    settings = BrokerSettings.from_values({"BROKER_TOPIC_PARTITIONS": "6"})

    assert settings.topic_partitions == 6


@pytest.mark.asyncio
async def test_broker_health_checks_required_topic_set() -> None:
    admin = FakeAdmin()

    result = await broker_health(admin)

    assert result["ok"] is True
    assert result["topics"] == ["task.intake"]
    assert result["bootstrap_servers"] == "127.0.0.1:9092"
    assert result["required_topic_count"] == len(required_topics())
    assert "task.results" in result["missing_topics"]
    assert admin.health_topics == required_topics()


@pytest.mark.asyncio
async def test_broker_health_reports_optional_lag() -> None:
    admin = FakeAdmin()

    result = await broker_health(
        admin,
        lag_targets=(BrokerLagTarget(group_id="task_manager", topics=(TOPICS.task_intake,)),),
    )

    assert result["lag"] == [
        {
            "group_id": "task_manager",
            "total_lag": 5,
            "topics": [{"topic": TOPICS.task_intake, "partitions": 2, "lag": 5}],
        }
    ]
