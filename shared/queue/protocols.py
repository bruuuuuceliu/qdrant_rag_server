"""Transport-neutral queue contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


class QueueFullError(RuntimeError):
    """Raised when a bounded queue cannot accept more messages."""


@dataclass(frozen=True, slots=True)
class QueueMessage:
    topic: str
    key: str
    payload: dict[str, Any]
    headers: dict[str, str] = field(default_factory=dict)


class QueueProducer(Protocol):
    async def publish(self, message: QueueMessage) -> None:
        """Publish one message."""


class QueueConsumer(Protocol):
    async def consume(self, topic: str) -> QueueMessage:
        """Receive one message from a topic."""


@runtime_checkable
class QueueBroker(QueueProducer, QueueConsumer, Protocol):
    """Unified broker protocol for publish/consume with topic management.

    This is the contract that network broker adapters (Kafka, NATS, Redis)
    should implement. LocalQueueBroker satisfies it today.
    """

    def task_done(self, topic: str) -> None:
        """Acknowledge one consumed message on the given topic."""

    def depth(self, topic: str) -> int:
        """Return approximate message count for a topic."""
