"""Ingestion service application bootstrap."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ingestion_service.server.consumer import IngestionRequestConsumer


@dataclass(slots=True)
class IngestionAppContext:
    enabled: bool
    topic: str
    consumer: IngestionRequestConsumer | None

    async def shutdown(self) -> None:
        if self.consumer is not None:
            await self.consumer.stop()


async def create_app(
    *,
    queue: Any,
    project_documents: Any,
    enabled: bool = True,
    topic: str = "ingestion.requests",
) -> IngestionAppContext:
    consumer: IngestionRequestConsumer | None = None
    if enabled:
        consumer = IngestionRequestConsumer(
            queue=queue,
            project_documents=project_documents,
            topic=topic,
        )
        consumer.start()

    return IngestionAppContext(
        enabled=enabled,
        topic=topic,
        consumer=consumer,
    )
