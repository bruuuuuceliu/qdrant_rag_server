"""Reusable async worker queue for ingest jobs."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Generic, TypeVar

from shared.queue import QueueFullError

T = TypeVar("T")

JobHandler = Callable[[str, T], Awaitable[None]]
QueueDepthCallback = Callable[[int], None]


class AsyncIngestWorkerQueue(Generic[T]):
    """Bounded async queue with a fixed set of worker tasks."""

    def __init__(
        self,
        *,
        worker_count: int,
        handler: JobHandler[T],
        maxsize: int = 0,
        on_queue_depth: QueueDepthCallback | None = None,
    ) -> None:
        self.queue: asyncio.Queue[tuple[str, T]] = asyncio.Queue(maxsize=maxsize)
        self._handler = handler
        self._on_queue_depth = on_queue_depth
        self.workers = [
            asyncio.create_task(self._worker_loop())
            for _ in range(worker_count)
        ]

    async def submit(self, job_id: str, item: T) -> None:
        try:
            self.queue.put_nowait((job_id, item))
        except asyncio.QueueFull as exc:
            raise QueueFullError("ingest queue is full") from exc
        self._record_queue_depth()

    async def join(self) -> None:
        await self.queue.join()

    def qsize(self) -> int:
        return self.queue.qsize()

    async def shutdown(self) -> None:
        for worker in self.workers:
            worker.cancel()
        await asyncio.gather(*self.workers, return_exceptions=True)

    async def _worker_loop(self) -> None:
        while True:
            try:
                job_id, item = await self.queue.get()
            except asyncio.CancelledError:
                return
            try:
                await self._handler(job_id, item)
            finally:
                self.queue.task_done()
                self._record_queue_depth()

    def _record_queue_depth(self) -> None:
        if self._on_queue_depth is not None:
            self._on_queue_depth(self.queue.qsize())
