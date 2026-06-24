"""Task manager server context."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from shared.contracts import MessageConsumer, TOPICS
from shared.runtime_health import RuntimeHealth
from task_manager_service.config import TaskManagerSettings
from task_manager_service.dispatcher import TaskManagerDispatcher


@dataclass(slots=True)
class TaskManagerServerContext:
    dispatcher: TaskManagerDispatcher
    intake_consumer: MessageConsumer
    domain_result_consumers: tuple[tuple[str, MessageConsumer], ...]
    helper_result_consumers: tuple[tuple[str, MessageConsumer], ...]
    settings: TaskManagerSettings = field(default_factory=TaskManagerSettings)
    _tasks: list[asyncio.Task[None]] = field(default_factory=list)

    def start(self) -> None:
        if self._tasks:
            return
        self._tasks = [
            asyncio.create_task(self._run_intake()),
            *(
                asyncio.create_task(self._run_domain_results(topic, consumer))
                for topic, consumer in self.domain_result_consumers
            ),
            *(
                asyncio.create_task(self._run_helper_results(topic, consumer))
                for topic, consumer in self.helper_result_consumers
            ),
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []

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
            and bool(self.domain_result_consumers)
            and bool(self.helper_result_consumers),
            dependencies={
                "broker_intake": self.intake_consumer is not None,
                "broker_domain_results": bool(self.domain_result_consumers),
                "broker_helper_results": bool(self.helper_result_consumers),
                "redis_status": redis_ready,
                "state_repository": getattr(self.dispatcher, "_state_repository", None) is not None,
            },
            details={
                "task_intake_topic": self.settings.task_intake_topic,
                "task_result_topic": self.settings.task_result_topic,
                "dead_letter_topic": self.settings.dead_letter_topic,
            },
        )

    async def run_intake_once(self) -> None:
        await self.dispatcher.run_once(self.intake_consumer)

    async def run_domain_result_once(
        self,
        topic: str | None = None,
        consumer: MessageConsumer | None = None,
    ) -> None:
        topic, consumer = self._select_consumer(
            self.domain_result_consumers,
            topic=topic,
            consumer=consumer,
            label="domain result",
        )
        envelope = await consumer.consume(topic)
        await self.dispatcher.dispatch_domain_result(envelope)

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

    async def _run_intake(self) -> None:
        while True:
            await self.dispatcher.run_once(self.intake_consumer)

    async def _run_domain_results(self, topic: str, consumer: MessageConsumer) -> None:
        while True:
            await self.run_domain_result_once(topic, consumer)

    async def _run_helper_results(self, topic: str, consumer: MessageConsumer) -> None:
        while True:
            await self.run_helper_result_once(topic, consumer)

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
            raise RuntimeError(f"task manager has no {label} consumers")
        return configured[0]
