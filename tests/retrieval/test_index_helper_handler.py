"""Retrieval-index helper broker handler tests."""

from __future__ import annotations

import pytest

from retrieval_service.indexing import IndexChunksResult, RetrievalIndexHelperHandler
from shared.contracts import MessageEnvelope, MessageType, TOPICS


class FakeProducer:
    def __init__(self) -> None:
        self.published: list[tuple[str, MessageEnvelope, str]] = []

    async def publish(self, topic: str, envelope: MessageEnvelope, *, key: str = "") -> None:
        self.published.append((topic, envelope, key))


class FakeIndexingService:
    def __init__(self) -> None:
        self.request = None

    async def index_chunks(self, request):
        self.request = request
        return IndexChunksResult(chunk_count=1, dense_enabled=True, sparse_enabled=False)


@pytest.mark.asyncio
async def test_retrieval_index_helper_handler_indexes_and_publishes_result() -> None:
    indexing_service = FakeIndexingService()
    producer = FakeProducer()
    handler = RetrievalIndexHelperHandler(indexing_service=indexing_service, producer=producer)

    result = await handler.handle(_command())

    assert indexing_service.request.collection_name == "docs"
    assert result.message_type == MessageType.HELPER_RESULT
    assert result.payload["helper"] == TOPICS.helper_retrieval_index_commands
    assert result.payload["result"] == {
        "ok": True,
        "chunk_count": 1,
        "dense_enabled": True,
        "sparse_enabled": False,
    }
    assert producer.published == [(TOPICS.helper_retrieval_index_results, result, "task-1")]


@pytest.mark.asyncio
async def test_retrieval_index_helper_handler_reports_missing_runtime() -> None:
    handler = RetrievalIndexHelperHandler(indexing_service=object())

    result = await handler.handle(_command())

    assert result.payload["result"]["ok"] is False


@pytest.mark.asyncio
async def test_retrieval_index_helper_handler_rejects_unknown_operation() -> None:
    handler = RetrievalIndexHelperHandler(indexing_service=FakeIndexingService())

    with pytest.raises(ValueError, match="unsupported"):
        await handler.handle(_command(operation="search"))


def _command(*, operation: str = "ingest") -> MessageEnvelope:
    return MessageEnvelope.create(
        producer="task_service",
        message_type=MessageType.HELPER_COMMAND,
        data_type="project_document",
        task_id="task-1",
        correlation_id="corr-1",
        payload={
            "operation": operation,
            "helper": TOPICS.helper_retrieval_index_commands,
            "plan": {
                "collection_name": "docs",
                "chunks": [
                    {
                        "document_id": "d1",
                        "chunk_id": "c1",
                        "chunk_index": 0,
                        "text": "hello",
                    }
                ],
            },
        },
    )
