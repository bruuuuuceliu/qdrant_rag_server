"""Ingestion helper broker server context."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field

from broker_service import BrokerSettings, create_redpanda_bus
from ingestion_service.server.domain_handler import IngestionHelperHandler
from shared.contracts import MessageConsumer, MessageProducer, TOPICS


@dataclass(slots=True)
class IngestionHelperServerContext:
    handler: IngestionHelperHandler
    consumer: MessageConsumer
    command_topic: str = TOPICS.helper_ingestion_commands
    producer: MessageProducer | None = None
    _task: asyncio.Task[None] | None = field(default=None, init=False)

    async def start_runtime(self) -> None:
        await _start_component(self.producer)
        await _start_component(self.consumer)
        self.start()

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)
        self._task = None
        await _stop_component(self.consumer)
        await _stop_component(self.producer)

    async def run_once(self) -> None:
        envelope = await self.consumer.consume(self.command_topic)
        await self.handler.handle(envelope)

    async def _run(self) -> None:
        while True:
            await self.run_once()


def create_helper_app(
    *,
    app: object,
    broker_settings: BrokerSettings | None = None,
    producer: MessageProducer | None = None,
    consumer: MessageConsumer | None = None,
    service_name: str = "ingestion_service",
    command_topic: str = TOPICS.helper_ingestion_commands,
) -> IngestionHelperServerContext:
    broker_settings = broker_settings or BrokerSettings.from_values(dict(os.environ))
    producer = producer or create_redpanda_bus(broker_settings)
    consumer = consumer or create_redpanda_bus(
        broker_settings,
        topic=command_topic,
        group_id=service_name,
    )
    return IngestionHelperServerContext(
        handler=IngestionHelperHandler(app=app, producer=producer),
        consumer=consumer,
        producer=producer,
        command_topic=command_topic,
    )


async def _start_component(component: object | None) -> None:
    start = getattr(component, "start", None)
    if start is not None:
        await start()


async def _stop_component(component: object | None) -> None:
    stop = getattr(component, "stop", None)
    if stop is not None:
        await stop()
