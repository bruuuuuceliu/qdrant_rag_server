"""Task service server context."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging

from shared.contracts import MessageConsumer
from shared.runtime_health import RuntimeHealth
from task_service.config import TaskServiceSettings
from task_service.dispatcher import TaskServiceDispatcher

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TaskServiceServerContext:
    dispatcher: TaskServiceDispatcher
    request_consumer: MessageConsumer
    project_plan_result_consumers: tuple[tuple[str, MessageConsumer], ...]
    helper_result_consumers: tuple[tuple[str, MessageConsumer], ...]
    settings: TaskServiceSettings = field(default_factory=TaskServiceSettings)
    _tasks: list[asyncio.Task[None]] = field(default_factory=list)

    async def start_runtime(self) -> None:
        await _start_component(getattr(self.dispatcher, "_producer", None))
        await _start_component(self.request_consumer)
        for _topic, consumer in self.project_plan_result_consumers:
            await _start_component(consumer)
        for _topic, consumer in self.helper_result_consumers:
            await _start_component(consumer)
        self.start()

    def start(self) -> None:
        if self._tasks:
            return
        self._tasks = [
            asyncio.create_task(self._run_requests()),
            *(
                asyncio.create_task(self._run_project_plan_results(topic, consumer))
                for topic, consumer in self.project_plan_result_consumers
            ),
            *(
                asyncio.create_task(self._run_helper_results(topic, consumer))
                for topic, consumer in self.helper_result_consumers
            ),
        ]
        if self.settings.recovery_enabled and self.dispatcher.recovery_supported:
            self._tasks.append(asyncio.create_task(self._run_recovery()))

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        for _topic, consumer in self.helper_result_consumers:
            await _stop_component(consumer)
        for _topic, consumer in self.project_plan_result_consumers:
            await _stop_component(consumer)
        await _stop_component(self.request_consumer)
        await _stop_component(getattr(self.dispatcher, "_producer", None))

    async def health(self) -> RuntimeHealth:
        return RuntimeHealth(
            service=self.settings.service_name,
            ready=self.request_consumer is not None
            and bool(self.project_plan_result_consumers)
            and bool(self.helper_result_consumers),
            dependencies={
                "broker_task_requests": self.request_consumer is not None,
                "broker_project_plan_results": bool(self.project_plan_result_consumers),
                "broker_helper_results": bool(self.helper_result_consumers),
                "state_repository": getattr(self.dispatcher, "_state_repository", None) is not None,
            },
            details={
                "task_request_topic": self.settings.task_request_topic,
                "project_plan_request_topic": self.settings.project_plan_request_topic,
                "task_event_topic": self.settings.task_event_topic,
                "task_result_topic": self.settings.task_result_topic,
                "dead_letter_topic": self.settings.dead_letter_topic,
                "recovery_enabled": self.settings.recovery_enabled,
                "helper_lease_seconds": self.settings.helper_lease_seconds,
                "retry_backoff_seconds": self.settings.retry_backoff_seconds,
            },
        )

    async def run_request_once(self) -> None:
        await self.dispatcher.run_once(self.request_consumer)
        await _commit_component(self.request_consumer)

    async def run_project_plan_result_once(
        self,
        topic: str | None = None,
        consumer: MessageConsumer | None = None,
    ) -> None:
        topic, consumer = self._select_consumer(
            self.project_plan_result_consumers,
            topic=topic,
            consumer=consumer,
            label="project plan result",
        )
        envelope = await consumer.consume(topic)
        await self.dispatcher.dispatch_project_plan_result(envelope)
        await _commit_component(consumer)

    async def run_helper_result_once(
        self,
        topic: str | None = None,
        consumer: MessageConsumer | None = None,
    ) -> None:
        topic, consumer = self._select_consumer(
            self.helper_result_consumers,
            topic=topic,
            consumer=consumer,
            label="helper result",
        )
        envelope = await consumer.consume(topic)
        await self.dispatcher.finalize_helper_result(envelope)
        await _commit_component(consumer)

    async def run_recovery_once(self) -> object:
        return await self.dispatcher.recover_due_helpers()

    async def _run_requests(self) -> None:
        while True:
            await self.run_request_once()

    async def _run_project_plan_results(self, topic: str, consumer: MessageConsumer) -> None:
        while True:
            await self.run_project_plan_result_once(topic, consumer)

    async def _run_helper_results(self, topic: str, consumer: MessageConsumer) -> None:
        while True:
            await self.run_helper_result_once(topic, consumer)

    async def _run_recovery(self) -> None:
        while True:
            try:
                await self.run_recovery_once()
            except Exception:
                logger.exception("task service recovery pass failed")
            await asyncio.sleep(self.settings.recovery_poll_seconds)

    def _select_consumer(
        self,
        configured: tuple[tuple[str, MessageConsumer], ...],
        *,
        topic: str | None,
        consumer: MessageConsumer | None,
        label: str,
    ) -> tuple[str, MessageConsumer]:
        if topic is not None and consumer is not None:
            return topic, consumer
        if not configured:
            raise RuntimeError(f"task service has no {label} consumers")
        if topic is not None:
            for configured_topic, configured_consumer in configured:
                if configured_topic == topic:
                    return configured_topic, configured_consumer
            raise RuntimeError(f"task service has no {label} consumer for topic {topic}")
        return configured[0]


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
