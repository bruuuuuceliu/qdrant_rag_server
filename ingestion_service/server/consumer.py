"""Queue consumer for ingestion request messages."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, is_dataclass
import logging
from typing import Any

from shared.queue import QueueMessage

logger = logging.getLogger(__name__)


class IngestionRequestConsumer:
    """Consumes queued ingest requests and delegates to a project-document client."""

    def __init__(
        self,
        *,
        queue: Any,
        project_documents: Any,
        topic: str = "ingestion.requests",
    ) -> None:
        self._queue = queue
        self._project_documents = project_documents
        self._topic = topic
        self._task: asyncio.Task[None] | None = None

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
        await asyncio.gather(self._task, return_exceptions=True)
        self._task = None

    async def _run(self) -> None:
        while True:
            try:
                message = await self._queue.consume(self._topic)
            except asyncio.CancelledError:
                return
            try:
                result = await self._project_documents.ingest(
                    dict(message.payload.get("request", message.payload))
                )
                await self._publish_response(
                    message,
                    ok=True,
                    result=result,
                )
            except Exception as exc:
                logger.exception("failed to process queued ingest request")
                await self._publish_response(
                    message,
                    ok=False,
                    error=str(exc),
                )
            finally:
                task_done = getattr(self._queue, "task_done", None)
                if task_done is not None:
                    task_done(self._topic)

    async def _publish_response(
        self,
        message: Any,
        *,
        ok: bool,
        result: Any = None,
        error: str = "",
    ) -> None:
        response_topic = str(
            message.payload.get("response_topic", f"{self._topic}.responses.{message.key}")
        )
        response_payload: dict[str, Any] = {
            "request_id": str(message.payload.get("request_id", message.key)),
            "ok": ok,
            "error": error,
        }
        if ok:
            response_payload["result"] = _result_to_payload(result)
        await self._queue.publish(
            QueueMessage(
                topic=response_topic,
                key=str(message.key),
                payload=response_payload,
                headers={
                    "correlation_id": str(message.key),
                    "request_topic": self._topic,
                },
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
