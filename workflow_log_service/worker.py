"""Workflow-log domain service process entrypoint."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

from broker_service import BrokerSettings
from shared.runtime_health import RuntimeHealth
from workflow_log_service.domain_app import (
    WorkflowLogDomainServerContext,
    WorkflowLogDomainSettings,
    create_default_domain_app,
)


@dataclass(slots=True)
class WorkflowLogWorkerContext:
    settings: WorkflowLogDomainSettings
    domain_app: WorkflowLogDomainServerContext

    async def shutdown(self) -> None:
        await self.domain_app.stop()

    async def health(self) -> RuntimeHealth:
        return RuntimeHealth(
            service=self.settings.service_name,
            ready=True,
            dependencies={
                "repository": True,
                "broker_consumer": getattr(self.domain_app, "consumer", None) is not None,
            },
            details={
                "db_path": str(self.settings.db_path),
                "command_topic": self.settings.command_topic,
            },
        )


async def create_worker_context(
    *,
    settings: WorkflowLogDomainSettings | None = None,
    broker_settings: BrokerSettings | None = None,
) -> WorkflowLogWorkerContext:
    settings = settings or WorkflowLogDomainSettings.from_values(dict(os.environ))
    domain_app = await create_default_domain_app(
        settings=settings,
        broker_settings=broker_settings,
    )
    return WorkflowLogWorkerContext(settings=settings, domain_app=domain_app)


async def serve_forever() -> None:
    context = await create_worker_context()
    context.domain_app.start()
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await context.shutdown()


def main() -> None:
    asyncio.run(serve_forever())


if __name__ == "__main__":
    main()
