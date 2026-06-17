"""Retrieval indexing worker app context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from retrieval_service.indexing.consumer import RetrievalIndexConsumer


@dataclass(slots=True)
class RetrievalIndexAppContext:
    enabled: bool
    topic: str
    consumer: RetrievalIndexConsumer | None

    async def shutdown(self) -> None:
        if self.consumer is not None:
            await self.consumer.stop()


async def create_app(
    *,
    queue: Any,
    indexing_service: Any,
    enabled: bool = True,
    topic: str = "retrieval.index.requests",
) -> RetrievalIndexAppContext:
    consumer: RetrievalIndexConsumer | None = None
    if enabled:
        consumer = RetrievalIndexConsumer(
            queue=queue,
            indexing_service=indexing_service,
            topic=topic,
        )
        consumer.start()
    return RetrievalIndexAppContext(
        enabled=enabled,
        topic=topic,
        consumer=consumer,
    )
