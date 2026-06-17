"""Retrieval API server context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from retrieval_service.retrieval import RetrievalApiHandler
from retrieval_service.retrieval import create_app as create_retrieval_app
from retrieval_service.server.queue import RetrievalApiQueueConsumer


@dataclass(slots=True)
class RetrievalApiServerContext:
    """Transport-ready retrieval API context backed by a retrieval app."""

    app: Any
    handler: RetrievalApiHandler

    async def search(
        self,
        payload: dict[str, Any],
        *,
        fallback_request_id: str,
    ) -> dict[str, Any]:
        return await self.handler.handle_search(
            payload,
            fallback_request_id=fallback_request_id,
        )

    async def delete_document(
        self,
        payload: dict[str, Any],
        *,
        fallback_request_id: str,
    ) -> dict[str, Any]:
        return await self.handler.handle_delete_document(
            payload,
            fallback_request_id=fallback_request_id,
        )

    async def get_raw_document(
        self,
        payload: dict[str, Any],
        *,
        fallback_request_id: str,
    ) -> dict[str, Any]:
        return await self.handler.handle_raw_document(
            payload,
            fallback_request_id=fallback_request_id,
        )

    async def shutdown(self) -> None:
        await self.app.shutdown()


@dataclass(slots=True)
class RetrievalApiQueueAppContext:
    """Retrieval API queue worker context."""

    enabled: bool
    topic: str
    api: RetrievalApiServerContext
    consumer: RetrievalApiQueueConsumer | None

    async def shutdown(self) -> None:
        if self.consumer is not None:
            await self.consumer.stop()
        await self.api.shutdown()


async def create_app(*, retrieval_service: Any) -> RetrievalApiServerContext:
    app = await create_retrieval_app(retrieval_service=retrieval_service)
    return RetrievalApiServerContext(
        app=app,
        handler=RetrievalApiHandler(app=app),
    )


async def create_queue_app(
    *,
    queue: Any,
    retrieval_service: Any,
    enabled: bool = True,
    topic: str = "retrieval.api.requests",
) -> RetrievalApiQueueAppContext:
    api = await create_app(retrieval_service=retrieval_service)
    consumer: RetrievalApiQueueConsumer | None = None
    if enabled:
        consumer = RetrievalApiQueueConsumer(queue=queue, api=api, topic=topic)
        consumer.start()
    return RetrievalApiQueueAppContext(
        enabled=enabled,
        topic=topic,
        api=api,
        consumer=consumer,
    )
