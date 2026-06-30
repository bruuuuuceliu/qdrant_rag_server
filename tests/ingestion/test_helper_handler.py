"""Ingestion helper broker handler tests."""

from __future__ import annotations

import pytest

from ingestion_service.server import IngestionHelperHandler
from shared.contracts import MessageEnvelope, MessageType, MessageValidationError, TOPICS


class FakeProducer:
    def __init__(self) -> None:
        self.published: list[tuple[str, MessageEnvelope, str]] = []

    async def publish(self, topic: str, envelope: MessageEnvelope, *, key: str = "") -> None:
        self.published.append((topic, envelope, key))


class FakeIngestionApp:
    def __init__(self) -> None:
        self.plan = None

    async def start_ingest(self, plan: dict[str, object]) -> dict[str, object]:
        self.plan = plan
        return {"ok": True, "job_id": "job-1"}


@pytest.mark.asyncio
async def test_ingestion_helper_handler_runs_ingest_and_publishes_result() -> None:
    app = FakeIngestionApp()
    producer = FakeProducer()
    handler = IngestionHelperHandler(app=app, producer=producer)

    result = await handler.handle(_command(operation="ingest"))

    assert app.plan == {"project_id": "p1"}
    assert result.message_type == MessageType.HELPER_RESULT
    assert result.payload["helper"] == TOPICS.helper_ingestion_commands
    assert result.payload["result"] == {"ok": True, "job_id": "job-1"}
    assert producer.published == [(TOPICS.helper_ingestion_results, result, "task-1")]


@pytest.mark.asyncio
async def test_ingestion_helper_handler_reports_missing_runtime() -> None:
    handler = IngestionHelperHandler(app=object())

    result = await handler.handle(_command(operation="ingest"))

    assert result.payload["result"]["ok"] is False


@pytest.mark.asyncio
async def test_ingestion_helper_handler_rejects_non_ingest_operation() -> None:
    handler = IngestionHelperHandler(app=FakeIngestionApp())

    with pytest.raises(ValueError, match="unsupported"):
        await handler.handle(_command(operation="search"))


@pytest.mark.asyncio
async def test_ingestion_helper_handler_rejects_missing_helper() -> None:
    handler = IngestionHelperHandler(app=FakeIngestionApp())

    with pytest.raises(MessageValidationError, match="helper"):
        await handler.handle(_command(operation="ingest", helper=""))


def _command(*, operation: str, helper: str = TOPICS.helper_ingestion_commands) -> MessageEnvelope:
    return MessageEnvelope.create(
        producer="task_service",
        message_type=MessageType.HELPER_COMMAND,
        data_type="project_document",
        task_id="task-1",
        correlation_id="corr-1",
        payload={"operation": operation, "helper": helper, "plan": {"project_id": "p1"}},
    )
