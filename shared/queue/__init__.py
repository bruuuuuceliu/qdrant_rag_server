"""Queue abstractions with Kafka-compatible message semantics."""

from shared.queue.local import LocalQueueBroker
from shared.queue.protocols import QueueConsumer, QueueFullError, QueueMessage, QueueProducer

__all__ = [
    "LocalQueueBroker",
    "QueueConsumer",
    "QueueFullError",
    "QueueMessage",
    "QueueProducer",
]
