"""Memory semantic-searcher port.

``MemorySearcher`` performs semantic chat-history/document retrieval over the
retrieval service. ``BrokerMemorySearcher`` publishes a ``memory_search`` helper
command and awaits the correlated reply; ``FakeMemorySearcher`` returns
deterministic hits for tests. The domain handler only ever depends on the port.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import uuid4

from shared.contracts import (
    HelperCommandPayload,
    HelperResultPayload,
    MessageEnvelope,
    MessageProducer,
    MessageType,
    TOPICS,
)


class MemorySearchError(RuntimeError):
    """Base error for memory search hand-off failures."""


class MemorySearchUpstreamError(MemorySearchError):
    """Raised when the retrieval search helper returned an error."""


class MemorySearchUnavailableError(MemorySearchError):
    """Raised when the retrieval search reply never arrives."""


class MemorySearcher(Protocol):
    """Port: semantic search over memory-indexed collections."""

    async def search(
        self,
        scope: Any,
        query: str,
        top_k: int,
        *,
        collection_name: str = "",
        session_ids: tuple[str, ...] = (),
    ) -> list[dict[str, Any]]:
        ...


class FakeMemorySearcher:
    """Deterministic in-process searcher returning configured hits."""

    def __init__(self, hits: list[dict[str, Any]] | None = None) -> None:
        self.hits: list[dict[str, Any]] = [dict(hit) for hit in (hits or [])]
        self.calls: list[dict[str, Any]] = []

    async def search(
        self,
        scope: Any,
        query: str,
        top_k: int,
        *,
        collection_name: str = "",
        session_ids: tuple[str, ...] = (),
    ) -> list[dict[str, Any]]:
        self.calls.append(
            {
                "owner_user_id": getattr(scope, "owner_user_id", ""),
                "agent_id": getattr(scope, "agent_id", ""),
                "query": query,
                "top_k": top_k,
                "collection_name": collection_name,
                "session_ids": tuple(session_ids),
            }
        )
        return [dict(hit) for hit in self.hits[:top_k]]


@dataclass(slots=True)
class BrokerMemorySearcher:
    """Publishes ``memory_search`` helper commands and awaits the reply."""

    producer: MessageProducer
    consumer: Any
    timeout_seconds: float = 10.0
    memory_collection_name: str = "agent_memory"
    _pending: dict[str, asyncio.Future[list[dict[str, Any]]]] = field(
        default_factory=dict,
        init=False,
    )

    async def search(
        self,
        scope: Any,
        query: str,
        top_k: int,
        *,
        collection_name: str = "",
        session_ids: tuple[str, ...] = (),
    ) -> list[dict[str, Any]]:
        correlation_id = uuid4().hex
        task_id = uuid4().hex
        loop = asyncio.get_running_loop()
        future: asyncio.Future[list[dict[str, Any]]] = loop.create_future()
        self._pending[correlation_id] = future
        envelope = MessageEnvelope.create(
            producer="memory_service",
            message_type=MessageType.HELPER_COMMAND,
            data_type="agent_memory",
            task_id=task_id,
            correlation_id=correlation_id,
            payload=HelperCommandPayload(
                operation="memory_search",
                helper=TOPICS.helper_retrieval_commands,
                attempt=1,
                plan={
                    "request_id": task_id,
                    "response_topic": TOPICS.helper_retrieval_results,
                    "request": {
                        "query_text": query,
                        "collection_name": collection_name or self.memory_collection_name,
                        "project_id": getattr(scope, "project_id", ""),
                        "user_id": getattr(scope, "owner_user_id", ""),
                        "agent_id": getattr(scope, "agent_id", ""),
                        "top_k": top_k,
                        "session_ids": list(session_ids),
                    },
                },
                source_message_id=task_id,
            ).to_payload(),
        )
        try:
            await self.producer.publish(
                TOPICS.helper_retrieval_commands,
                envelope,
                key=task_id,
            )
            return await asyncio.wait_for(future, timeout=self.timeout_seconds)
        except asyncio.TimeoutError as exc:
            raise MemorySearchUnavailableError(
                f"memory search timed out after {self.timeout_seconds}s"
            ) from exc
        finally:
            self._pending.pop(correlation_id, None)

    async def handle_result(self, envelope: MessageEnvelope) -> None:
        """Feed a correlated helper reply from the retrieval-reply consumer loop."""

        payload = HelperResultPayload.from_envelope(envelope)
        future = self._pending.get(envelope.correlation_id)
        if future is None or future.done():
            return
        if payload.error:
            future.set_exception(MemorySearchUpstreamError(payload.error))
            return
        # The retrieval helper returns a RetrievalResponseEnvelope mapping
        # ({request_id, ok, result: {hits: [...]}}); unwrap the inner result.
        result = payload.result if isinstance(payload.result, dict) else {}
        inner = result.get("result") if isinstance(result.get("result"), dict) else result
        hits = inner.get("hits", []) if isinstance(inner.get("hits"), list) else []
        future.set_result([dict(hit) for hit in hits])
