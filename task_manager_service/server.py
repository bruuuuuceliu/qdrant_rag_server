"""Task manager server context."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from shared.contracts import MessageConsumer
from shared.runtime_health import RuntimeHealth
from task_manager_service.config import TaskManagerSettings
from task_manager_service.dispatcher import TaskManagerDispatcher


@dataclass(slots=True)
class TaskManagerServerContext:
    dispatcher: TaskManagerDispatcher
    intake_consumer: MessageConsumer
    task_event_consumer: MessageConsumer
    task_result_consumer: MessageConsumer
    settings: TaskManagerSettings = field(default_factory=TaskManagerSettings)
    _tasks: list[asyncio.Task[None]] = field(default_factory=list)

    async def start_runtime(self) -> None:
        await _start_component(getattr(self.dispatcher, "_producer", None))
        await _start_component(self.intake_consumer)
        await _start_component(self.task_event_consumer)
        await _start_component(self.task_result_consumer)
        self.start()

    def start(self) -> None:
        if self._tasks:
            return
        self._tasks = [
            asyncio.create_task(self._run_intake()),
            asyncio.create_task(self._run_task_events()),
            asyncio.create_task(self._run_task_results()),
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        await _stop_component(self.task_result_consumer)
        await _stop_component(self.task_event_consumer)
        await _stop_component(self.intake_consumer)
        await _stop_component(getattr(self.dispatcher, "_producer", None))

    async def health(self) -> RuntimeHealth:
        status_store = getattr(self.dispatcher, "_status_store", None)
        redis_ready = status_store is None
        if status_store is not None:
            ping = getattr(status_store, "ping", None)
            if ping is not None:
                try:
                    redis_ready = bool(await ping())
                except Exception:
                    redis_ready = False
        return RuntimeHealth(
            service=self.settings.service_name,
            ready=redis_ready
            and self.intake_consumer is not None
            and self.task_event_consumer is not None
            and self.task_result_consumer is not None,
            dependencies={
                "broker_intake": self.intake_consumer is not None,
                "broker_task_events": self.task_event_consumer is not None,
                "broker_task_results": self.task_result_consumer is not None,
                "redis_status": redis_ready,
            },
            details={
                "task_intake_topic": self.settings.task_intake_topic,
                "task_request_topic": self.settings.task_request_topic,
                "task_event_topic": self.settings.task_event_topic,
                "task_result_topic": self.settings.task_result_topic,
            },
        )

    async def run_intake_once(self) -> None:
        await self.dispatcher.run_once(self.intake_consumer)
        await _commit_component(self.intake_consumer)

    async def run_task_event_once(self, consumer: MessageConsumer | None = None) -> None:
        consumer = consumer or self.task_event_consumer
        envelope = await consumer.consume(self.settings.task_event_topic)
        await self.dispatcher.update_from_task_event(envelope)
        await _commit_component(consumer)

    async def run_task_result_once(self, consumer: MessageConsumer | None = None) -> None:
        consumer = consumer or self.task_result_consumer
        envelope = await consumer.consume(self.settings.task_result_topic)
        await self.dispatcher.update_from_task_result(envelope)
        await _commit_component(consumer)

    async def _run_intake(self) -> None:
        while True:
            await self.run_intake_once()

    async def _run_task_events(self) -> None:
        while True:
            await self.run_task_event_once()

    async def _run_task_results(self) -> None:
        while True:
            await self.run_task_result_once()


async def _start_component(component: object | None) -> None:
    start = getattr(component, "start", None)
    if start is not None:
        await start()


async def _stop_component(component: object | None) -> None:
    stop = getattr(component, "stop", None)
    if stop is not None:
        await stop()


async def _commit_component(component: object | None) -> None:
    commit = getattr(component, "commit", None)
    if commit is not None:
        await commit()
