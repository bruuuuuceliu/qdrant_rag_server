"""Queue consumer for retrieval indexing requests."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, is_dataclass
import logging
from typing import Any

from retrieval_service.indexing.commands import RetrievalIndexCommand
from retrieval_service.indexing.service import IndexingService
from shared.queue import QueueBroker, QueueMessage

logger = logging.getLogger(__name__)


class RetrievalIndexConsumer:
    """Consumes indexing commands and delegates to `IndexingService`."""

    def __init__(
        self,
        *,
        queue: QueueBroker,
        indexing_service: IndexingService,
        topic: str = "retrieval.index.requests",
    ) -> None:
        self._queue = queue
        self._indexing_service = indexing_service
        self._topic = topic
        self._task: asyncio.Task[None] | None = None
        self._inflight_tasks: set[asyncio.Task[None]] = set()

    @property
    def topic(self) -> str:
        return self._topic

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        tasks: list[asyncio.Task[None]] = [self._task]
        if self._inflight_tasks:
            for task in self._inflight_tasks:
                task.cancel()
            tasks.extend(self._inflight_tasks)
        await asyncio.gather(*tasks, return_exceptions=True)
        self._task = None
        self._inflight_tasks.clear()

    async def _run(self) -> None:
        while True:
            try:
                message = await self._queue.consume(self._topic)
            except asyncio.CancelledError:
                return

            self._queue.task_done(self._topic)
            task = asyncio.create_task(self._process_message(message))
            self._inflight_tasks.add(task)
            task.add_done_callback(self._inflight_tasks.discard)

    async def _process_message(self, message: QueueMessage) -> None:
        try:
            command = RetrievalIndexCommand.from_payload(
                message.payload,
                fallback_request_id=message.key,
            )
            result = await self._indexing_service.index_chunks(command.to_index_request())
            await self._publish_response(
                command,
                message_key=message.key,
                ok=True,
                result=_result_to_payload(result),
            )
            logger.debug(
                "retrieval indexing completed: request_id=%s job_id=%s chunks=%s",
                command.request_id,
                command.job_id,
                getattr(result, "chunk_count", 0),
            )
        except Exception as exc:
            request_id = str(message.payload.get("request_id") or message.key)
            job_id = str(message.payload.get("job_id") or request_id)
            logger.exception(
                "retrieval indexing failed: request_id=%s job_id=%s",
                request_id,
                job_id,
            )
            await self._publish_error_response(
                message,
                request_id=request_id,
                job_id=job_id,
                message_key=message.key,
                error={"message": str(exc), "type": type(exc).__name__},
            )

    async def _publish_response(
        self,
        command: RetrievalIndexCommand,
        *,
        message_key: str,
        ok: bool,
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> None:
        if not command.response_topic:
            return
        payload: dict[str, Any] = {
            "request_id": command.request_id,
            "job_id": command.job_id,
            "ok": ok,
        }
        if result is not None:
            payload["result"] = result
        if error is not None:
            payload["error"] = error
        await self._queue.publish(
            QueueMessage(
                topic=command.response_topic,
                key=message_key,
                payload=payload,
                headers={"correlation_id": command.request_id, "request_topic": self._topic},
            )
        )

    async def _publish_error_response(
        self,
        message: QueueMessage,
        *,
        request_id: str,
        job_id: str,
        message_key: str,
        error: dict[str, Any],
    ) -> None:
        response_topic = str(message.payload.get("response_topic") or "")
        if not response_topic:
            return
        await self._queue.publish(
            QueueMessage(
                topic=response_topic,
                key=message_key,
                payload={
                    "request_id": request_id,
                    "job_id": job_id,
                    "ok": False,
                    "error": error,
                },
                headers={"correlation_id": request_id, "request_topic": self._topic},
            )
        )


def _result_to_payload(result: Any) -> dict[str, Any]:
    if result is None:
        return {}
    if is_dataclass(result):
        return asdict(result)
    if isinstance(result, dict):
        return dict(result)
    return dict(getattr(result, "__dict__", {}))
