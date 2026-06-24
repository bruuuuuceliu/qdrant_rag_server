"""Project domain broker server context."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field

from broker_service import BrokerSettings, create_redpanda_bus
from configs.config import get_int_value, get_value
from project_service.adapters import ProjectAdapterRegistry, ProjectAdapterResolver, WebsiteProjectAdapter
from project_service.config import SQLiteProjectConfigRepository
from project_service.domain_handler import ProjectDomainHandler
from project_service.gateway import AsyncConcurrencyLimiter, RagGateway
from project_service.planning import ProjectPlanningService
from shared.contracts import MessageConsumer, MessageProducer, TOPICS
from shared.runtime_health import RuntimeHealth


@dataclass(slots=True)
class ProjectDomainServerContext:
    handler: ProjectDomainHandler
    consumer: MessageConsumer
    command_topic: str = TOPICS.domain_project_commands
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

    async def health(self) -> RuntimeHealth:
        return RuntimeHealth(
            service="project_service",
            ready=self.consumer is not None and self.handler is not None,
            dependencies={
                "broker_consumer": self.consumer is not None,
                "planning": getattr(self.handler, "_planning", None) is not None,
            },
            details={"command_topic": self.command_topic},
        )

    async def _run(self) -> None:
        while True:
            await self.run_once()


def create_domain_app(
    *,
    planning: object,
    broker_settings: BrokerSettings | None = None,
    producer: MessageProducer | None = None,
    consumer: MessageConsumer | None = None,
    service_name: str = "project_service",
    command_topic: str = TOPICS.domain_project_commands,
) -> ProjectDomainServerContext:
    broker_settings = broker_settings or BrokerSettings()
    producer = producer or create_redpanda_bus(broker_settings)
    consumer = consumer or create_redpanda_bus(
        broker_settings,
        topic=command_topic,
        group_id=service_name,
    )
    return ProjectDomainServerContext(
        handler=ProjectDomainHandler(planning=planning, producer=producer),
        consumer=consumer,
        command_topic=command_topic,
    )


@dataclass(frozen=True, slots=True)
class ProjectDomainSettings:
    service_name: str = "project_service"
    command_topic: str = TOPICS.domain_project_commands
    config_db_path: str = "/var/lib/rag/config.db"
    max_per_project: int = 20
    max_per_user: int = 5

    @classmethod
    def from_values(cls, values: dict[str, str]) -> "ProjectDomainSettings":
        return cls(
            service_name=get_value(values, "PROJECT_SERVICE_NAME", "project_service"),
            command_topic=get_value(
                values,
                "PROJECT_DOMAIN_COMMAND_TOPIC",
                TOPICS.domain_project_commands,
            ),
            config_db_path=get_value(values, "PROJECT_CONFIG_DB_PATH", "/var/lib/rag/config.db"),
            max_per_project=get_int_value(values, "PROJECT_MAX_PER_PROJECT", 20),
            max_per_user=get_int_value(values, "PROJECT_MAX_PER_USER", 5),
        )


async def create_default_domain_app(
    *,
    settings: ProjectDomainSettings | None = None,
    broker_settings: BrokerSettings | None = None,
) -> ProjectDomainServerContext:
    settings = settings or ProjectDomainSettings()
    config_repo = SQLiteProjectConfigRepository(settings.config_db_path)
    await config_repo.initialize()
    registry = ProjectAdapterRegistry()
    registry.register(WebsiteProjectAdapter(config_repo=config_repo))
    gateway = RagGateway(
        adapter_resolver=ProjectAdapterResolver(
            project_types=config_repo,
            registry=registry,
        ),
        concurrency_limiter=AsyncConcurrencyLimiter(
            max_per_project=settings.max_per_project,
            max_per_user=settings.max_per_user,
        ),
    )
    planning = ProjectPlanningService(gateway=gateway)
    return create_domain_app(
        planning=planning,
        broker_settings=broker_settings,
        service_name=settings.service_name,
        command_topic=settings.command_topic,
    )


async def serve_forever() -> None:
    context = await create_default_domain_app(
        settings=ProjectDomainSettings.from_values(dict(os.environ)),
    )
    context.start()
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await context.stop()


def main() -> None:
    asyncio.run(serve_forever())


if __name__ == "__main__":
    main()
