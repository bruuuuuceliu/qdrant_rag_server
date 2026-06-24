"""Storage helper broker handler tests."""

from __future__ import annotations

import pytest

from shared.contracts import MessageEnvelope, MessageType, TOPICS
from storage_node import FilesystemStorageService, StorageHelperHandler


class FakeProducer:
    def __init__(self) -> None:
        self.published: list[tuple[str, MessageEnvelope, str]] = []

    async def publish(self, topic: str, envelope: MessageEnvelope, *, key: str = "") -> None:
        self.published.append((topic, envelope, key))


@pytest.mark.asyncio
async def test_storage_helper_handler_puts_and_publishes_result(tmp_path) -> None:
    storage = FilesystemStorageService(root=tmp_path)
    producer = FakeProducer()
    handler = StorageHelperHandler(storage=storage, producer=producer)

    result = await handler.handle(_command(operation="put", plan={"key": "a.txt", "value": "hello"}))

    assert result.message_type == MessageType.HELPER_RESULT
    assert result.payload["helper"] == TOPICS.helper_storage_commands
    assert result.payload["result"] == {"ok": True, "key": "a.txt"}
    assert producer.published == [(TOPICS.helper_storage_results, result, "task-1")]
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "hello"


@pytest.mark.asyncio
async def test_storage_helper_handler_rejects_unknown_operation(tmp_path) -> None:
    handler = StorageHelperHandler(storage=FilesystemStorageService(root=tmp_path))

    with pytest.raises(ValueError, match="unsupported"):
        await handler.handle(_command(operation="copy", plan={"key": "a.txt"}))


@pytest.mark.asyncio
async def test_storage_helper_handler_uses_plan_operation_for_ingest_followup(tmp_path) -> None:
    storage = FilesystemStorageService(root=tmp_path)
    handler = StorageHelperHandler(storage=storage)

    result = await handler.handle(
        _command(
            operation="ingest",
            plan={"operation": "put", "key": "raw/p1/u1/d1", "value": "raw text"},
        )
    )

    assert result.payload["result"] == {"ok": True, "key": "raw/p1/u1/d1"}
    assert (tmp_path / "raw" / "p1" / "u1" / "d1").read_text(encoding="utf-8") == "raw text"


def _command(*, operation: str, plan: dict[str, object]) -> MessageEnvelope:
    return MessageEnvelope.create(
        producer="task_manager_service",
        message_type=MessageType.HELPER_COMMAND,
        data_type="project_document",
        task_id="task-1",
        correlation_id="corr-1",
        payload={
            "operation": operation,
            "helper": TOPICS.helper_storage_commands,
            "plan": plan,
        },
    )
