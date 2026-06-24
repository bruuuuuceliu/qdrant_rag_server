"""Optional Redpanda/Kafka consumer lag probes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from broker_service.config import BrokerSettings


@dataclass(frozen=True, slots=True)
class BrokerLagTarget:
    group_id: str
    topics: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.group_id.strip():
            raise ValueError("lag target group_id must be nonblank")
        if not self.topics:
            raise ValueError("lag target topics must be nonempty")
        if any(not topic.strip() for topic in self.topics):
            raise ValueError("lag target topics must be nonblank")


@dataclass(frozen=True, slots=True)
class BrokerTopicLag:
    topic: str
    partitions: int
    lag: int

    def to_payload(self) -> dict[str, object]:
        return {
            "topic": self.topic,
            "partitions": self.partitions,
            "lag": self.lag,
        }


@dataclass(frozen=True, slots=True)
class BrokerLagReport:
    group_id: str
    total_lag: int
    topics: tuple[BrokerTopicLag, ...]

    def to_payload(self) -> dict[str, object]:
        return {
            "group_id": self.group_id,
            "total_lag": self.total_lag,
            "topics": [topic.to_payload() for topic in self.topics],
        }


def parse_broker_lag_targets(raw: str | None) -> tuple[BrokerLagTarget, ...]:
    if raw is None or not raw.strip():
        return ()
    targets: list[BrokerLagTarget] = []
    for item in raw.split(";"):
        item = item.strip()
        if not item:
            continue
        if ":" not in item:
            raise ValueError("lag target must use group_id:topic,topic format")
        group_id, topics_raw = item.split(":", 1)
        topics = tuple(topic.strip() for topic in topics_raw.split(",") if topic.strip())
        targets.append(BrokerLagTarget(group_id=group_id.strip(), topics=topics))
    return tuple(targets)


async def broker_lag(
    admin: Any,
    targets: tuple[BrokerLagTarget, ...],
    *,
    settings: BrokerSettings | None = None,
) -> tuple[BrokerLagReport, ...]:
    if not targets:
        return ()
    settings = settings or admin.settings
    reports: list[BrokerLagReport] = []
    for target in targets:
        topic_lags: list[BrokerTopicLag] = []
        for topic in target.topics:
            configured_topic = settings.topic(topic)
            partition_lags = await _topic_partition_lags(admin, target.group_id, configured_topic)
            topic_lags.append(
                BrokerTopicLag(
                    topic=configured_topic,
                    partitions=len(partition_lags),
                    lag=sum(partition_lags),
                )
            )
        reports.append(
            BrokerLagReport(
                group_id=target.group_id,
                total_lag=sum(topic.lag for topic in topic_lags),
                topics=tuple(topic_lags),
            )
        )
    return tuple(reports)


async def _topic_partition_lags(admin: Any, group_id: str, topic: str) -> tuple[int, ...]:
    if hasattr(admin, "consumer_group_lag"):
        values = await admin.consumer_group_lag(group_id, topic)
        return tuple(max(0, int(value)) for value in values)
    if hasattr(admin, "list_consumer_group_offsets"):
        return await _aiokafka_topic_partition_lags(admin, group_id, topic)
    raise TypeError("admin client does not support consumer lag probing")


async def _aiokafka_topic_partition_lags(admin: Any, group_id: str, topic: str) -> tuple[int, ...]:
    try:
        from aiokafka import TopicPartition
    except ImportError as exc:
        raise RuntimeError("aiokafka is required for consumer lag probing") from exc

    partitions = await admin.describe_topics([topic])
    partition_ids = _partition_ids(partitions, topic)
    if not partition_ids:
        return ()

    topic_partitions = [TopicPartition(topic, partition_id) for partition_id in partition_ids]
    end_offsets = await admin.list_offsets(topic_partitions)
    committed_offsets = await admin.list_consumer_group_offsets(group_id)
    lags: list[int] = []
    for topic_partition in topic_partitions:
        end_offset = _offset_value(_lookup_offset(end_offsets, topic_partition))
        committed = _offset_value(_lookup_offset(committed_offsets, topic_partition))
        if committed < 0:
            committed = end_offset
        lags.append(max(0, end_offset - committed))
    return tuple(lags)


def _partition_ids(described_topics: Any, topic: str) -> tuple[int, ...]:
    for described in described_topics or ():
        name = _field(described, "topic", _field(described, "name", ""))
        if name != topic:
            continue
        partitions = _field(described, "partitions", ())
        return tuple(int(_field(partition, "partition", partition)) for partition in partitions)
    return ()


def _lookup_offset(offsets: Any, topic_partition: Any) -> Any:
    if isinstance(offsets, dict):
        return offsets.get(topic_partition)
    for item in offsets or ():
        item_tp = _field(item, "topic_partition", _field(item, "tp", None))
        if item_tp == topic_partition:
            return item
    return None


def _offset_value(value: Any) -> int:
    if value is None:
        return -1
    if isinstance(value, int):
        return value
    for name in ("offset", "position"):
        offset = getattr(value, name, None)
        if offset is not None:
            return int(offset)
    if isinstance(value, tuple) and value:
        return int(value[0])
    return int(value)


def _field(value: Any, name: str, default: Any) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)
