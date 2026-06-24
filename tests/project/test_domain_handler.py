"""Project domain broker handler tests."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from project_service import ProjectDomainHandler
from shared.contracts import MessageEnvelope, MessageType, TOPICS


class FakeProducer:
    def __init__(self) -> None:
        self.published: list[tuple[str, MessageEnvelope, str]] = []

    async def publish(self, topic: str, envelope: MessageEnvelope, *, key: str = "") -> None:
        self.published.append((topic, envelope, key))


class FakePlanning:
    def __init__(self) -> None:
        self.requests: list[object] = []

    async def plan_ingest(self, request: object) -> object:
        self.requests.append(request)
        return _Plan(project_id="p1", operation="ingest")

    async def plan_search(self, request: object) -> object:
        self.requests.append(request)
        return _Plan(project_id="p1", operation="search")

    async def plan_delete(self, request: object) -> object:
        self.requests.append(request)
        return _Plan(project_id="p1", operation="delete")


@dataclass(frozen=True, slots=True)
class _Plan:
    project_id: str
    operation: str
    raw_plan: object = "internal"
    request: object = "internal-request"


@pytest.mark.asyncio
async def test_project_domain_handler_returns_and_publishes_plan_result() -> None:
    producer = FakeProducer()
    planning = FakePlanning()
    handler = ProjectDomainHandler(planning=planning, producer=producer)
    command = _command(operation="ingest")

    result = await handler.handle(command)

    assert result.message_type == MessageType.DOMAIN_RESULT
    assert result.task_id == "task-1"
    assert result.payload["operation"] == "ingest"
    assert result.payload["plan"] == {"project_id": "p1", "operation": "ingest"}
    assert producer.published == [(TOPICS.domain_project_results, result, "task-1")]
    assert planning.requests == [{"project_id": "p1"}]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["search", "delete"])
async def test_project_domain_handler_supports_search_and_delete(operation: str) -> None:
    handler = ProjectDomainHandler(planning=FakePlanning())

    result = await handler.handle(_command(operation=operation))

    assert result.payload["plan"]["operation"] == operation


@pytest.mark.asyncio
async def test_project_domain_handler_rejects_unknown_operation() -> None:
    handler = ProjectDomainHandler(planning=FakePlanning())

    with pytest.raises(ValueError, match="unsupported"):
        await handler.handle(_command(operation="export"))


def _command(*, operation: str) -> MessageEnvelope:
    return MessageEnvelope.create(
        producer="task_manager_service",
        message_type=MessageType.DOMAIN_COMMAND,
        data_type="project_document",
        task_id="task-1",
        correlation_id="corr-1",
        payload={"operation": operation, "request": {"project_id": "p1"}},
    )

