"""Queue consumer for workflow log events."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from workflow_log_service.models import WorkflowLogEntry
from workflow_log_service.repository import WorkflowLogRepository

logger = logging.getLogger(__name__)


class WorkflowLogConsumer:
    """Consumes queue messages and persists workflow log entries."""

    def __init__(
        self,
        *,
        queue: Any,
        repository: WorkflowLogRepository,
        topic: str = "ingestion.events",
    ) -> None:
        self._queue = queue
        self._repository = repository
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
                await self._repository.append(WorkflowLogEntry.from_message(message))
            except Exception:
                logger.exception("failed to persist workflow log event")
            finally:
                task_done = getattr(self._queue, "task_done", None)
                if task_done is not None:
                    task_done(self._topic)
