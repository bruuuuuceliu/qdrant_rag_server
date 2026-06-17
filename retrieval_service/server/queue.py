"""Queue transport for retrieval API requests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import uuid
from typing import Any

from retrieval_service.retrieval import RetrievalResponseEnvelope
from shared.queue import QueueBroker, QueueMessage


class RetrievalApiQueueTimeoutError(TimeoutError):
    """Raised when a retrieval API queue response is not received in time."""

    def __init__(self, *, request_id: str, timeout: float) -> None:
        super().__init__(
            f"retrieval API request {request_id} timed out after {timeout} seconds"
        )
        self.request_id = request_id
        self.timeout = timeout


class RetrievalApiQueueConsumer:
    """Consumes retrieval API requests and publishes response envelopes."""

    def __init__(
        self,
        *,
        queue: QueueBroker,
        api: Any,
        topic: str = "retrieval.api.requests",
    ) -> None:
        self._queue = queue
        self._api = api
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
        payload = dict(message.payload)
        request_id = str(payload.get("request_id") or message.key)
        response_topic = str(
            payload.get("response_topic") or f"{self._topic}.responses.{request_id}"
        )
        operation = str(payload.get("operation") or "")
        request_payload = _request_payload(payload)

        if operation == "search":
            response = await self._api.search(
                request_payload,
                fallback_request_id=request_id,
            )
        elif operation == "delete_document":
            response = await self._api.delete_document(
                request_payload,
                fallback_request_id=request_id,
            )
        elif operation == "get_raw_document":
            response = await self._api.get_raw_document(
                request_payload,
                fallback_request_id=request_id,
            )
        else:
            response = RetrievalResponseEnvelope.failure(
                request_id=request_id,
                code="validation_error",
                message=f"unknown retrieval operation: {operation or '<missing>'}",
                retryable=False,
            ).to_mapping()

        await self._queue.publish(
            QueueMessage(
                topic=response_topic,
                key=message.key,
                payload=response,
                headers={
                    "correlation_id": request_id,
                    "request_topic": self._topic,
                },
            )
        )


@dataclass(slots=True)
class RetrievalApiQueueClient:
    """Queue-backed retrieval API client returning response-envelope mappings."""

    queue: QueueBroker
    topic: str = "retrieval.api.requests"
    response_timeout: float = 30.0

    async def search(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("search", payload)

    async def delete_document(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("delete_document", payload)

    async def get_raw_document(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("get_raw_document", payload)

    async def _request(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        request_id = str(payload.get("request_id") or uuid.uuid4())
        response_topic = str(
            payload.get("response_topic") or f"{self.topic}.responses.{request_id}"
        )
        await self.queue.publish(
            QueueMessage(
                topic=self.topic,
                key=request_id,
                payload={
                    "request_id": request_id,
                    "response_topic": response_topic,
                    "operation": operation,
                    "request": _request_payload(payload),
                },
                headers={"correlation_id": request_id},
            )
        )
        try:
            response = await asyncio.wait_for(
                self.queue.consume(response_topic),
                timeout=self.response_timeout,
            )
        except TimeoutError as exc:
            raise RetrievalApiQueueTimeoutError(
                request_id=request_id,
                timeout=self.response_timeout,
            ) from exc
        self.queue.task_done(response_topic)
        return dict(response.payload)


def _request_payload(payload: dict[str, Any]) -> dict[str, Any]:
    request = payload.get("request")
    if isinstance(request, dict):
        return dict(request)
    ignored = {"request_id", "response_topic", "operation"}
    return {key: value for key, value in payload.items() if key not in ignored}
