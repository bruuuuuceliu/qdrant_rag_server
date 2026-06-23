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
    jobs: Any,
    ingestion_service: IngestionService,
    retrieval_queue: Any,
    retrieval_index_topic: str = "retrieval.index.requests",
    retrieval_index_response_timeout: float = 30.0,
    enabled: bool = True,
    topic: str = "ingestion.requests",
) -> IngestionAppContext:
    consumer: IngestionRequestConsumer | None = None
    if enabled:
        if jobs is None:
            raise ValueError("ingestion job repository is required")
        if ingestion_service is None:
            raise ValueError("ingestion service is required")
        if retrieval_queue is None:
            raise ValueError("retrieval index queue is required")
        consumer = IngestionRequestConsumer(
            queue=queue,
            jobs=jobs,
            ingestion_service=ingestion_service,
            retrieval_queue=retrieval_queue,
            retrieval_index_topic=retrieval_index_topic,
            retrieval_index_response_timeout=retrieval_index_response_timeout,
            topic=topic,
        )
        consumer.start()

    return IngestionAppContext(
        enabled=enabled,
        topic=topic,
        jobs=jobs,
        consumer=consumer,
    )
