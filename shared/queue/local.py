"""In-process bounded queue backend for local development and tests."""

from __future__ import annotations

import asyncio

from shared.queue.protocols import QueueFullError, QueueMessage


class LocalQueueBroker:
    """A small topic queue with publish/consume semantics."""

    def __init__(self, *, maxsize: int = 0) -> None:
        self._maxsize = maxsize
        self._topics: dict[str, asyncio.Queue[QueueMessage]] = {}

    async def publish(self, message: QueueMessage) -> None:
        queue = self._queue(message.topic)
        try:
            queue.put_nowait(message)
        except asyncio.QueueFull as exc:
            raise QueueFullError(f"queue topic {message.topic!r} is full") from exc

    async def consume(self, topic: str) -> QueueMessage:
        return await self._queue(topic).get()

    def task_done(self, topic: str) -> None:
        self._queue(topic).task_done()

    async def join(self, topic: str) -> None:
        await self._queue(topic).join()

    def depth(self, topic: str) -> int:
        return self._queue(topic).qsize()

    def _queue(self, topic: str) -> asyncio.Queue[QueueMessage]:
        if topic not in self._topics:
            self._topics[topic] = asyncio.Queue(maxsize=self._maxsize)
        return self._topics[topic]
