"""Workflow log service application bootstrap."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from workflow_log_service.consumer import WorkflowLogConsumer
from workflow_log_service.repository import (
    MemoryWorkflowLogRepository,
    SQLiteWorkflowLogRepository,
    WorkflowLogRepository,
)


@dataclass(slots=True)
class WorkflowLogAppContext:
    enabled: bool
    topic: str
    repository: WorkflowLogRepository
    consumer: WorkflowLogConsumer | None

    async def shutdown(self) -> None:
        if self.consumer is not None:
            await self.consumer.stop()


async def create_app(
    *,
    queue: Any,
    enabled: bool = True,
    topic: str = "ingestion.events",
    db_path: str | Path | None = None,
) -> WorkflowLogAppContext:
    repository: WorkflowLogRepository
    consumer: WorkflowLogConsumer | None = None
    if enabled:
        if db_path is None:
            repository = MemoryWorkflowLogRepository()
        else:
            repository = SQLiteWorkflowLogRepository(db_path)
            await repository.initialize()
        consumer = WorkflowLogConsumer(
            queue=queue,
            repository=repository,
            topic=topic,
        )
        consumer.start()
    else:
        repository = MemoryWorkflowLogRepository()

    return WorkflowLogAppContext(
        enabled=enabled,
        topic=topic,
        repository=repository,
        consumer=consumer,
    )
