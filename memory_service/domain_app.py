"""Memory domain broker server context.

Mirrors ``workflow_log_service/domain_app.py`` with the memory service's three
consumers: the memory command consumer (group ``memory_service``), the identity
event consumer (group ``memory_service.identity``), and the retrieval-reply
consumer that feeds awaited ``memory_search`` replies (group
``memory_service.retrieval``).
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field

from broker_service import BrokerSettings, create_redpanda_bus
from memory_service.compression import CompressionPolicy, CondenseV1Policy
from memory_service.config import MemoryServiceSettings
from memory_service.domain_handler import MemoryDomainHandler
from memory_service.identity import BrokerIdentitySource, FakeIdentitySource
from memory_service.indexer import BrokerMemoryIndexer, FakeMemoryIndexer
from memory_service.repository import SQLiteMemoryRepository
from memory_service.searcher import BrokerMemorySearcher, FakeMemorySearcher
from shared.contracts import MessageConsumer, MessageProducer, TOPICS


@dataclass(slots=True)
class MemoryDomainServerContext:
    handler: MemoryDomainHandler
    consumer: MessageConsumer
    identity_consumer: MessageConsumer | None = None
    retrieval_consumer: MessageConsumer | None = None
    producer: MessageProducer | None = None
    command_topic: str = TOPICS.domain_memory_commands
    identity_topic: str = TOPICS.identity_user_events
    retrieval_results_topic: str = TOPICS.helper_retrieval_results
    _task: asyncio.Task[None] | None = field(default=None, init=False)
    _identity_task: asyncio.Task[None] | None = field(default=None, init=False)
    _retrieval_task: asyncio.Task[None] | None = field(default=None, init=False)

    async def start_runtime(self) -> None:
        await _start_component(self.producer)
        await _start_component(self.consumer)
        await _start_component(self.identity_consumer)
        await _start_component(self.retrieval_consumer)
        self.start()

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())
        if self.identity_consumer is not None and (
            self._identity_task is None or self._identity_task.done()
        ):
            self._identity_task = asyncio.create_task(self._run_identity_events())
        if self.retrieval_consumer is not None and (
            self._retrieval_task is None or self._retrieval_task.done()
        ):
            self._retrieval_task = asyncio.create_task(self._run_retrieval_replies())

    async def stop(self) -> None:
        tasks = [
            task
            for task in (self._task, self._identity_task, self._retrieval_task)
            if task is not None
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._task = None
        self._identity_task = None
        self._retrieval_task = None
        await _stop_component(self.retrieval_consumer)
        await _stop_component(self.identity_consumer)
        await _stop_component(self.consumer)
        await _stop_component(self.producer)

    async def run_once(self) -> None:
        envelope = await self.consumer.consume(self.command_topic)
        await self.handler.handle(envelope)
        await _commit_component(self.consumer)

    async def run_identity_once(self) -> None:
        if self.identity_consumer is None:
            raise RuntimeError("memory identity consumer is not configured")
        message = await self.identity_consumer.consume(self.identity_topic)
        identity_source = getattr(self.handler, "_identity_source", None)
        handle_event = getattr(identity_source, "handle_event", None)
        if handle_event is not None:
            event = dict(getattr(message, "payload", message))
            await handle_event(event)
        await _commit_component(self.identity_consumer)

    async def run_retrieval_once(self) -> None:
        if self.retrieval_consumer is None:
            raise RuntimeError("memory retrieval-reply consumer is not configured")
        envelope = await self.retrieval_consumer.consume(self.retrieval_results_topic)
        searcher = getattr(self.handler, "_searcher", None)
        handle_result = getattr(searcher, "handle_result", None)
        if handle_result is not None:
            await handle_result(envelope)
        await _commit_component(self.retrieval_consumer)

    async def _run(self) -> None:
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - one bad message must not kill the loop
                await _commit_component(self.consumer)

    async def _run_identity_events(self) -> None:
        while True:
            try:
                await self.run_identity_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                await _commit_component(self.identity_consumer)

    async def _run_retrieval_replies(self) -> None:
        while True:
            try:
                await self.run_retrieval_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                await _commit_component(self.retrieval_consumer)


def create_domain_app(
    *,
    repository: object,
    compression: CompressionPolicy | None = None,
    indexer: object = None,
    searcher: object = None,
    identity_source: object = None,
    service_auth: object = None,
    producer: MessageProducer | None = None,
    consumer: MessageConsumer | None = None,
    identity_consumer: MessageConsumer | None = None,
    retrieval_consumer: MessageConsumer | None = None,
    settings: MemoryServiceSettings | None = None,
    broker_settings: BrokerSettings | None = None,
) -> MemoryDomainServerContext:
    broker_settings = broker_settings or BrokerSettings.from_values(dict(os.environ))
    settings = settings or MemoryServiceSettings()
    producer = producer or create_redpanda_bus(broker_settings)
    consumer = consumer or create_redpanda_bus(
        broker_settings,
        topic=settings.command_topic,
        group_id=settings.service_name,
    )
    # The identity-server publishes raw outbox JSON (no shared envelope) to
    # identity.user.events; consume it raw so BrokerIdentitySource sees the
    # event payload directly.
    identity_consumer = identity_consumer or create_redpanda_bus(
        broker_settings,
        topic=settings.identity_topic,
        group_id=f"{settings.service_name}.identity",
        raw=True,
    )
    retrieval_consumer = retrieval_consumer or create_redpanda_bus(
        broker_settings,
        topic=settings.retrieval_results_topic,
        group_id=f"{settings.service_name}.retrieval",
    )
    if indexer is None:
        indexer = FakeMemoryIndexer()
    if searcher is None:
        searcher = FakeMemorySearcher()
    if identity_source is None:
        identity_source = FakeIdentitySource(repository)
    if compression is None:
        compression = CondenseV1Policy()
    handler = MemoryDomainHandler(
        repository=repository,
        compression=compression,
        indexer=indexer,
        searcher=searcher,
        identity_source=identity_source,
        producer=producer,
        service_auth=service_auth or settings.service_auth,
        result_topic=settings.result_topic,
        memory_collection_name=settings.memory_collection_name,
        documents_collection_name=settings.documents_collection_name,
        include_merged=settings.include_merged,
    )
    return MemoryDomainServerContext(
        handler=handler,
        consumer=consumer,
        identity_consumer=identity_consumer,
        retrieval_consumer=retrieval_consumer,
        producer=producer,
        command_topic=settings.command_topic,
        identity_topic=settings.identity_topic,
        retrieval_results_topic=settings.retrieval_results_topic,
    )


async def create_default_domain_app(
    *,
    settings: MemoryServiceSettings | None = None,
    broker_settings: BrokerSettings | None = None,
) -> MemoryDomainServerContext:
    """Build the runtime composition root from settings (fake modes for local)."""
    settings = settings or MemoryServiceSettings()
    repository = SQLiteMemoryRepository(settings.db_path)
    await repository.initialize()

    producer = (
        None
        if (settings.index_mode == "fake" and settings.search_mode == "fake")
        else create_redpanda_bus(broker_settings or BrokerSettings.from_values(dict(os.environ)))
    )
    if settings.index_mode == "fake":
        indexer: object = FakeMemoryIndexer()
    else:
        indexer = BrokerMemoryIndexer(
            producer=producer,  # type: ignore[arg-type]
            collection_name=settings.memory_collection_name,
        )
    if settings.search_mode == "fake":
        searcher: object = FakeMemorySearcher()
    else:
        searcher = BrokerMemorySearcher(
            producer=producer,  # type: ignore[arg-type]
            consumer=None,
            memory_collection_name=settings.memory_collection_name,
        )
    if settings.identity_mode == "fake":
        identity_source: object = FakeIdentitySource(repository)
    else:
        identity_source = BrokerIdentitySource(repository)

    return create_domain_app(
        repository=repository,
        compression=CondenseV1Policy(),
        indexer=indexer,
        searcher=searcher,
        identity_source=identity_source,
        service_auth=settings.service_auth,
        producer=producer,
        settings=settings,
        broker_settings=broker_settings,
    )


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
