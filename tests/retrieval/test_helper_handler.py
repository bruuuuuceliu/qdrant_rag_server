"""Retrieval helper broker handler tests."""

from __future__ import annotations

import pytest

from retrieval_service.retrieval.contracts import MemorySearchCommand
from retrieval_service.server import RetrievalHelperHandler
from shared.contracts import MessageEnvelope, MessageType, MessageValidationError, TOPICS


class FakeProducer:
    def __init__(self) -> None:
        self.published: list[tuple[str, MessageEnvelope, str]] = []

    async def publish(self, topic: str, envelope: MessageEnvelope, *, key: str = "") -> None:
        self.published.append((topic, envelope, key))


class FakeRetrievalApi:
    def __init__(self) -> None:
        self.search_payload = None
        self.memory_search_payload = None
        self.delete_payload = None

    async def search(self, payload: dict[str, object], *, fallback_request_id: str) -> dict[str, object]:
        self.search_payload = payload
        return {"ok": True, "hits": []}

    async def handle_memory_search(
        self,
        payload: dict[str, object],
        *,
        fallback_request_id: str,
    ) -> dict[str, object]:
        self.memory_search_payload = payload
        return {"ok": True, "hits": [{"source_id": "mem_1", "text": "x", "score": 0.9}]}

    async def delete_document(
        self,
        payload: dict[str, object],
        *,
        fallback_request_id: str,
    ) -> dict[str, object]:
        self.delete_payload = payload
        return {"ok": True, "deleted": True}


@pytest.mark.asyncio
async def test_retrieval_helper_handler_runs_search_and_publishes_result() -> None:
    api = FakeRetrievalApi()
    producer = FakeProducer()
    handler = RetrievalHelperHandler(api=api, producer=producer)

    result = await handler.handle(_command(operation="search"))

    assert api.search_payload == {"project_id": "p1"}
    assert result.message_type == MessageType.HELPER_RESULT
    assert result.payload["helper"] == TOPICS.helper_retrieval_commands
    assert result.payload["attempt"] == 2
    assert result.payload["result"] == {"ok": True, "hits": []}
    assert producer.published == [(TOPICS.helper_retrieval_results, result, "task-1")]


@pytest.mark.asyncio
async def test_retrieval_helper_handler_runs_delete() -> None:
    api = FakeRetrievalApi()
    handler = RetrievalHelperHandler(api=api)

    result = await handler.handle(_command(operation="delete"))

    assert api.delete_payload == {"project_id": "p1"}
    assert result.payload["result"] == {"ok": True, "deleted": True}


@pytest.mark.asyncio
async def test_retrieval_helper_handler_reports_missing_runtime() -> None:
    handler = RetrievalHelperHandler(api=object())

    result = await handler.handle(_command(operation="search"))

    assert result.payload["result"]["ok"] is False


@pytest.mark.asyncio
async def test_retrieval_helper_handler_runs_memory_search() -> None:
    api = FakeRetrievalApi()
    handler = RetrievalHelperHandler(api=api)

    result = await handler.handle(_command(operation="memory_search"))

    assert api.memory_search_payload is not None
    assert result.payload["result"]["ok"] is True
    assert result.payload["result"]["hits"][0]["source_id"] == "mem_1"


def test_memory_search_command_parses_session_ids_and_top_k() -> None:
    """Memory-search hand-off must not drop session_ids/top_k (A1 regression)."""
    command = MemorySearchCommand.from_payload(
        {
            "request_id": "r1",
            "response_topic": "helper.retrieval.results",
            "request": {
                "query_text": "hello",
                "collection_name": "agent_memory",
                "agent_id": "agent_1",
                "top_k": 7,
                "session_ids": ["con_1", "con_2"],
            },
        },
        fallback_request_id="fb",
    )
    assert command.session_ids == ("con_1", "con_2")
    assert command.top_k == 7
    service_request = command.to_service_request()
    assert service_request.session_ids == ("con_1", "con_2")
    assert service_request.top_k == 7


@pytest.mark.asyncio
async def test_retrieval_helper_handler_rejects_unknown_operation() -> None:
    handler = RetrievalHelperHandler(api=FakeRetrievalApi())

    with pytest.raises(ValueError, match="unsupported"):
        await handler.handle(_command(operation="ingest"))


@pytest.mark.asyncio
async def test_retrieval_helper_handler_rejects_missing_helper() -> None:
    handler = RetrievalHelperHandler(api=FakeRetrievalApi())

    with pytest.raises(MessageValidationError, match="helper"):
        await handler.handle(_command(operation="search", helper=""))


def _command(*, operation: str, helper: str = TOPICS.helper_retrieval_commands) -> MessageEnvelope:
    return MessageEnvelope.create(
        producer="task_service",
        message_type=MessageType.HELPER_COMMAND,
        data_type="project_document",
        task_id="task-1",
        correlation_id="corr-1",
        payload={"operation": operation, "helper": helper, "plan": {"project_id": "p1"}, "attempt": 2},
    )
