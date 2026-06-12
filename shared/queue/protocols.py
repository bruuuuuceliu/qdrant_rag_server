"""Transport-neutral queue contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class QueueFullError(RuntimeError):
    """Raised when a bounded local queue cannot accept more messages."""


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
