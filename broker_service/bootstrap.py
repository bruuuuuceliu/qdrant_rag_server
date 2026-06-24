"""Broker topic bootstrap helpers."""

from __future__ import annotations

from broker_service.config import BrokerSettings
from broker_service.lag import BrokerLagTarget, broker_lag
from broker_service.redpanda import RedpandaAdmin
from shared.contracts import TOPICS


def required_topics() -> tuple[str, ...]:
    return TOPICS.all()


async def bootstrap_topics(
    admin: RedpandaAdmin,
    *,
    settings: BrokerSettings | None = None,
) -> None:
    settings = settings or admin.settings
    await admin.ensure_topics(required_topics(), partitions=settings.topic_partitions)


async def broker_health(
    admin: RedpandaAdmin,
    *,
    lag_targets: tuple[BrokerLagTarget, ...] = (),
) -> dict[str, object]:
    required = required_topics()
    health = await admin.health(required_topics=required)
    payload = health.to_payload()
    configured_topics = tuple(admin.settings.topic(topic) for topic in required)
    available_topics = set(str(topic) for topic in getattr(health, "topics", payload.get("topics", ())))
    payload.update(
        {
            "bootstrap_servers": admin.settings.bootstrap_servers,
            "topic_prefix": admin.settings.topic_prefix,
            "required_topic_count": len(required),
            "missing_topics": [
                topic for topic in configured_topics if topic not in available_topics
            ],
        }
    )
    if lag_targets:
        payload["lag"] = [
            report.to_payload()
            for report in await broker_lag(admin, lag_targets, settings=admin.settings)
        ]
    return payload
