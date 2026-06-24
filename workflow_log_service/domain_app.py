"""Workflow-log domain broker server context."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from broker_service import BrokerSettings, create_redpanda_bus
from configs.config import get_value
from shared.contracts import MessageConsumer, MessageProducer, TOPICS
from workflow_log_service.domain_handler import WorkflowLogDomainHandler
from workflow_log_service.repository import SQLiteWorkflowLogRepository


@dataclass(slots=True)
class WorkflowLogDomainServerContext:
    handler: WorkflowLogDomainHandler
    consumer: MessageConsumer
    command_topic: str = TOPICS.domain_workflow_log_commands
    _task: asyncio.Task[None] | None = field(default=None, init=False)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)
        self._task = None

    async def run_once(self) -> None:
        envelope = await self.consumer.consume(self.command_topic)
        await self.handler.handle(envelope)

    async def _run(self) -> None:
        while True:
            await self.run_once()


def create_domain_app(
    *,
    repository: object,
    broker_settings: BrokerSettings | None = None,
    producer: MessageProducer | None = None,
    consumer: MessageConsumer | None = None,
    service_name: str = "workflow_log_service",
    command_topic: str = TOPICS.domain_workflow_log_commands,
) -> WorkflowLogDomainServerContext:
    broker_settings = broker_settings or BrokerSettings()
    producer = producer or create_redpanda_bus(broker_settings)
    consumer = consumer or create_redpanda_bus(
        broker_settings,
        topic=command_topic,
        group_id=service_name,
    )
    return WorkflowLogDomainServerContext(
        handler=WorkflowLogDomainHandler(repository=repository, producer=producer),
        consumer=consumer,
        command_topic=command_topic,
    )


@dataclass(frozen=True, slots=True)
class WorkflowLogDomainSettings:
    service_name: str = "workflow_log_service"
    command_topic: str = TOPICS.domain_workflow_log_commands
    db_path: Path = Path("/var/lib/rag/workflow_log.db")

    @classmethod
    def from_values(cls, values: dict[str, str]) -> "WorkflowLogDomainSettings":
        return cls(
            service_name=get_value(values, "WORKFLOW_LOG_SERVICE_NAME", "workflow_log_service"),
            command_topic=get_value(
                values,
                "WORKFLOW_LOG_DOMAIN_COMMAND_TOPIC",
                TOPICS.domain_workflow_log_commands,
            ),
            db_path=Path(
                get_value(values, "WORKFLOW_LOG_DB_PATH", "/var/lib/rag/workflow_log.db")
            ),
        )


async def create_default_domain_app(
    *,
    settings: WorkflowLogDomainSettings | None = None,
    broker_settings: BrokerSettings | None = None,
) -> WorkflowLogDomainServerContext:
    settings = settings or WorkflowLogDomainSettings()
    repository = SQLiteWorkflowLogRepository(settings.db_path)
    await repository.initialize()
    return create_domain_app(
        repository=repository,
        broker_settings=broker_settings,
        service_name=settings.service_name,
        command_topic=settings.command_topic,
    )
