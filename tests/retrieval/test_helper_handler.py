"""Retrieval helper broker handler tests."""

from __future__ import annotations

import pytest

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
        self.delete_payload = None

    async def search(self, payload: dict[str, object], *, fallback_request_id: str) -> dict[str, object]:
        self.search_payload = payload
        return {"ok": True, "hits": []}

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
