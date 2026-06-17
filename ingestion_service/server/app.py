"""Ingestion service application bootstrap."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ingestion_service.server.consumer import IngestionRequestConsumer
from ingestion_service.service import IngestionService


@dataclass(slots=True)
class IngestionAppContext:
    enabled: bool
    topic: str
    jobs: Any | None
    consumer: IngestionRequestConsumer | None

    async def shutdown(self) -> None:
        if self.consumer is not None:
            await self.consumer.stop()


async def create_app(
    *,
    queue: Any,
    project_documents: Any,
    jobs: Any | None = None,
    ingestion_service: IngestionService | None = None,
    retrieval_queue: Any | None = None,
    retrieval_index_topic: str = "retrieval.index.requests",
    enabled: bool = True,
    topic: str = "ingestion.requests",
) -> IngestionAppContext:
    consumer: IngestionRequestConsumer | None = None
    if enabled:
        consumer = IngestionRequestConsumer(
            queue=queue,
            project_documents=project_documents,
            jobs=jobs,
            ingestion_service=ingestion_service,
            retrieval_queue=retrieval_queue,
            retrieval_index_topic=retrieval_index_topic,
            topic=topic,
        )
        consumer.start()

    return IngestionAppContext(
        enabled=enabled,
        topic=topic,
        jobs=jobs,
        consumer=consumer,
    )
