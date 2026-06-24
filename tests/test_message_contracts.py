"""Broker message contract tests."""

from __future__ import annotations

import pytest

from shared.contracts import (
    DomainCommandPayload,
    DeadLetterPayload,
    DomainResultPayload,
    HelperCommandPayload,
    HelperResultPayload,
    MessageEnvelope,
    MessageType,
    MessageValidationError,
    TOPICS,
    TaskIntakePayload,
    TaskResultPayload,
    TaskStartedPayload,
    TaskStatus,
    TaskStatusRecord,
    domain_command_topic,
    domain_result_topic,
)


def test_message_envelope_round_trips_mapping() -> None:
    envelope = MessageEnvelope.create(
        producer="manager_service",
        message_type=MessageType.REQUEST_ACCEPTED,
        data_type="project_document",
        payload={"operation": "search"},
        task_id="task-1",
        correlation_id="corr-1",
        headers={"tenant_id": "tenant-1"},
    )

    parsed = MessageEnvelope.from_mapping(envelope.to_mapping())

    assert parsed.message_id == envelope.message_id
    assert parsed.task_id == "task-1"
    assert parsed.correlation_id == "corr-1"
    assert parsed.headers == {"tenant_id": "tenant-1"}
    assert parsed.payload == {"operation": "search"}


def test_message_envelope_rejects_missing_required_fields() -> None:
    with pytest.raises(MessageValidationError, match="message_id"):
        MessageEnvelope.from_mapping(
            {
                "correlation_id": "corr-1",
                "task_id": "task-1",
                "producer": "manager_service",
                "message_type": "request.accepted",
                "data_type": "project_document",
                "schema_version": "1",
                "created_at": "2026-06-23T00:00:00+00:00",
                "payload": {},
            }
        )


def test_message_envelope_rejects_non_mapping_payload() -> None:
    with pytest.raises(MessageValidationError, match="payload"):
        MessageEnvelope.from_mapping(
            {
                "message_id": "msg-1",
                "correlation_id": "corr-1",
                "task_id": "task-1",
                "producer": "manager_service",
                "message_type": "request.accepted",
                "data_type": "project_document",
                "schema_version": "1",
                "created_at": "2026-06-23T00:00:00+00:00",
                "payload": [],
            }
        )


def test_message_envelope_rejects_unknown_message_type_and_schema_version() -> None:
    base = {
        "message_id": "msg-1",
        "correlation_id": "corr-1",
        "task_id": "task-1",
        "producer": "manager_service",
        "message_type": "request.accepted",
        "data_type": "project_document",
        "schema_version": "1",
        "created_at": "2026-06-23T00:00:00+00:00",
        "payload": {},
    }

    with pytest.raises(MessageValidationError, match="message_type"):
        MessageEnvelope.from_mapping({**base, "message_type": "unknown"})
    with pytest.raises(MessageValidationError, match="schema_version"):
        MessageEnvelope.from_mapping({**base, "schema_version": "2"})


def test_topic_set_has_unique_topic_names() -> None:
    topics = TOPICS.all()

    assert TOPICS.task_intake == "task.intake"
    assert TOPICS.task_dead_letters == "task.dead_letters"
    assert len(topics) == len(set(topics))


@pytest.mark.parametrize(
    ("data_type", "command_topic", "result_topic"),
    [
        ("project_document", TOPICS.domain_project_commands, TOPICS.domain_project_results),
        ("workflow_log", TOPICS.domain_workflow_log_commands, TOPICS.domain_workflow_log_results),
        ("agent_memory", TOPICS.domain_memory_commands, TOPICS.domain_memory_results),
        ("custom", TOPICS.domain_other_commands, TOPICS.domain_other_results),
    ],
)
def test_domain_topic_routing(data_type: str, command_topic: str, result_topic: str) -> None:
    assert domain_command_topic(data_type) == command_topic
    assert domain_result_topic(data_type) == result_topic


def test_task_intake_payload_validates_envelope_type_and_request_mapping() -> None:
    envelope = MessageEnvelope.create(
        producer="manager_service",
        message_type=MessageType.REQUEST_ACCEPTED,
        data_type="project_document",
        task_id="task-1",
        correlation_id="corr-1",
        payload={
            "operation": "ingest",
            "request": {"project_id": "p1"},
            "context": {"request_id": "req-1"},
        },
    )

    payload = TaskIntakePayload.from_envelope(envelope)

    assert payload.operation == "ingest"
    assert payload.request == {"project_id": "p1"}
    assert payload.context == {"request_id": "req-1"}


def test_domain_command_payload_round_trips_payload() -> None:
    payload = DomainCommandPayload(
        operation="search",
        request={"query": "hello"},
        context={"request_id": "req-1"},
        source_message_id="msg-1",
    )

    parsed = DomainCommandPayload.from_payload(payload.to_payload())

    assert parsed == payload


def test_domain_result_payload_rejects_non_mapping_plan() -> None:
    with pytest.raises(MessageValidationError, match="plan"):
        DomainResultPayload.from_payload({"operation": "search", "plan": []})


def test_domain_result_payload_carries_failure_metadata() -> None:
    payload = DomainResultPayload.from_payload(
        {
            "operation": "search",
            "result": {"ok": False},
            "attempt": 2,
            "retryable": True,
            "error": "timeout",
        }
    )

    assert payload.attempt == 2
    assert payload.retryable is True
    assert payload.error == "timeout"
    assert payload.to_payload()["attempt"] == 2


def test_helper_command_payload_requires_helper() -> None:
    with pytest.raises(MessageValidationError, match="helper"):
        HelperCommandPayload.from_payload({"operation": "search", "plan": {}})


def test_helper_result_payload_uses_producer_as_helper_fallback() -> None:
    envelope = MessageEnvelope.create(
        producer="retrieval_service",
        message_type=MessageType.HELPER_RESULT,
        data_type="project_document",
        task_id="task-1",
        correlation_id="corr-1",
        payload={"operation": "search", "result": {"ok": True}},
    )

    payload = HelperResultPayload.from_envelope(envelope)

    assert payload.helper == "retrieval_service"
    assert payload.result == {"ok": True}


def test_helper_result_payload_rejects_invalid_attempt() -> None:
    with pytest.raises(MessageValidationError, match="attempt"):
        HelperResultPayload.from_payload(
            {
                "operation": "search",
                "helper": "retrieval",
                "attempt": 0,
            }
        )


def test_task_started_and_result_payloads_validate_status() -> None:
    started = TaskStartedPayload.from_payload({"operation": "search"})
    result = TaskResultPayload.from_payload(
        {"operation": "search", "status": TaskStatus.COMPLETED, "result": {"hits": []}}
    )

    assert started.status == TaskStatus.RUNNING
    assert result.status == TaskStatus.COMPLETED
    assert result.result == {"hits": []}
    with pytest.raises(MessageValidationError, match="status"):
        TaskResultPayload.from_payload({"operation": "search", "status": "done"})


def test_dead_letter_payload_round_trips_repair_context() -> None:
    payload = DeadLetterPayload(
        operation="search",
        source_topic=TOPICS.helper_retrieval_commands,
        source_message_id="source-1",
        failed_message_id="failed-1",
        attempt=3,
        retryable=True,
        error="timeout",
        result={"ok": False},
        context={"helper": TOPICS.helper_retrieval_commands},
    )

    parsed = DeadLetterPayload.from_payload(payload.to_payload())

    assert parsed == payload


def test_task_status_record_validates_required_fields_and_status() -> None:
    record = TaskStatusRecord(task_id="task-1", status=TaskStatus.RUNNING)

    assert TaskStatusRecord.from_mapping(record.to_mapping()) == record
    with pytest.raises(ValueError, match="task_id"):
        TaskStatusRecord(task_id="", status=TaskStatus.RUNNING)
    with pytest.raises(ValueError, match="status"):
        TaskStatusRecord(task_id="task-1", status="done")
