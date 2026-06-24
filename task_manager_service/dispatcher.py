"""Task manager dispatch core."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from shared.contracts import (
    MessageConsumer,
    MessageEnvelope,
    MessageProducer,
    MessageType,
    TOPICS,
    DomainCommandPayload,
    DomainResultPayload,
    DeadLetterPayload,
    HelperCommandPayload,
    HelperResultPayload,
    TaskResultPayload,
    TaskStartedPayload,
    TaskStatusRecord,
    TaskStatus,
    TaskStatusStore,
    TaskIntakePayload,
    domain_command_topic,
)
from task_manager_service.config import TaskManagerSettings
from task_manager_service.repository import TaskStateRepository


@dataclass(frozen=True, slots=True)
class DispatchResult:
    task_id: str
    data_type: str
    operation: str
    domain_topic: str


@dataclass(frozen=True, slots=True)
class HelperDispatchResult:
    task_id: str
    operation: str
    helper_topics: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FinalizeResult:
    task_id: str
    status: str
    result_topic: str


@dataclass(frozen=True, slots=True)
class RetryPlan:
    operation: str
    plan: dict[str, Any]


class TaskManagerDispatcher:
    """Consumes task intake and dispatches the first domain command."""

    def __init__(
        self,
        *,
        producer: MessageProducer,
        status_store: TaskStatusStore | None = None,
        state_repository: TaskStateRepository | None = None,
        settings: TaskManagerSettings | None = None,
    ) -> None:
        self._producer = producer
        self._status_store = status_store
        self._state_repository = state_repository
        self._settings = settings or TaskManagerSettings()

    async def dispatch_intake(self, envelope: MessageEnvelope) -> DispatchResult:
        payload = TaskIntakePayload.from_envelope(envelope)
        operation = payload.operation
        domain_topic = domain_command_topic(envelope.data_type)
        await self._write_status(envelope, operation=operation, status=TaskStatus.RUNNING)
        await self._publish_task_started(envelope, operation=operation)
        await self._publish_domain_command(envelope, payload=payload, topic=domain_topic)
        return DispatchResult(
            task_id=envelope.task_id,
            data_type=envelope.data_type,
            operation=operation,
            domain_topic=domain_topic,
        )

    async def run_once(self, consumer: MessageConsumer) -> DispatchResult:
        envelope = await consumer.consume(self._settings.task_intake_topic)
        return await self.dispatch_intake(envelope)

    async def dispatch_domain_result(self, envelope: MessageEnvelope) -> HelperDispatchResult:
        payload = DomainResultPayload.from_envelope(envelope)
        if envelope.data_type == "workflow_log":
            final = await self.finalize_domain_result(envelope)
            return HelperDispatchResult(
                task_id=final.task_id,
                operation=payload.operation,
                helper_topics=(),
            )
        operation = payload.operation
        helper_topics = _helper_topics(operation)
        if self._state_repository is not None:
            await self._state_repository.set_expected_helpers(envelope.task_id, helper_topics)
        for topic in helper_topics:
            if self._state_repository is not None:
                await self._state_repository.record_helper_plan(
                    envelope.task_id,
                    topic,
                    operation=operation,
                    plan=payload.plan,
                )
            await self._publish_helper_command(envelope, payload=payload, topic=topic)
        await self._write_status(envelope, operation=operation, status=TaskStatus.DISPATCHED)
        return HelperDispatchResult(
            task_id=envelope.task_id,
            operation=operation,
            helper_topics=helper_topics,
        )

    async def finalize_domain_result(self, envelope: MessageEnvelope) -> FinalizeResult:
        payload = DomainResultPayload.from_envelope(envelope)
        result = _result_with_failure_metadata(payload.result, payload)
        status = TaskStatus.COMPLETED if result.get("ok", True) is not False else TaskStatus.FAILED
        await self._write_status(
            envelope,
            operation=payload.operation,
            status=status,
            result=result,
            ttl_seconds=self._settings.completed_ttl_seconds,
        )
        final = MessageEnvelope.create(
            producer=self._settings.service_name,
            message_type=MessageType.TASK_RESULT,
            data_type=envelope.data_type,
            task_id=envelope.task_id,
            correlation_id=envelope.correlation_id,
            payload=TaskResultPayload(
                operation=payload.operation,
                status=status,
                result=result,
                source_message_id=envelope.message_id,
            ).to_payload(),
        )
        await self._producer.publish(
            self._settings.task_result_topic,
            final,
            key=envelope.task_id,
        )
        return FinalizeResult(
            task_id=envelope.task_id,
            status=status,
            result_topic=self._settings.task_result_topic,
        )

    async def finalize_helper_result(self, envelope: MessageEnvelope) -> FinalizeResult:
        payload = HelperResultPayload.from_envelope(envelope)
        operation = payload.operation
        result = _result_with_failure_metadata(payload.result, payload)
        status = TaskStatus.COMPLETED if result.get("ok", True) is not False else TaskStatus.FAILED
        helper = payload.helper
        if self._state_repository is not None:
            existing = await self._state_repository.get(envelope.task_id)
            if existing is not None and existing.final_published:
                return FinalizeResult(
                    task_id=envelope.task_id,
                    status=existing.final_status,
                    result_topic="",
                )
            if _should_retry(payload, self._settings.max_attempts):
                retry_plan = _retry_plan(existing, helper, fallback_operation=operation)
                await self._publish_helper_command_from_plan(
                    envelope,
                    operation=retry_plan.operation,
                    plan=retry_plan.plan,
                    topic=helper,
                    attempt=payload.attempt + 1,
                    source_message_id=payload.source_message_id or envelope.message_id,
                )
                await self._write_status(
                    envelope,
                    operation=operation,
                    status=TaskStatus.RUNNING,
                    result=result,
                )
                return FinalizeResult(
                    task_id=envelope.task_id,
                    status=TaskStatus.RUNNING.value,
                    result_topic="",
                )
            state = await self._state_repository.mark_helper_result(
                envelope.task_id,
                helper,
                ok=status == "completed",
                result=result,
            )
            followups = _followup_plans_from_ingestion_result(operation, helper, result)
            if status == TaskStatus.COMPLETED and followups:
                await self._state_repository.add_expected_helpers(
                    envelope.task_id,
                    tuple(topic for topic, _plan in followups),
                )
                for topic, plan in followups:
                    await self._state_repository.record_helper_plan(
                        envelope.task_id,
                        topic,
                        operation=str(plan.get("operation") or operation),
                        plan=plan,
                    )
                    await self._publish_helper_command_from_plan(
                        envelope,
                        operation=str(plan.get("operation") or operation),
                        plan=plan,
                        topic=topic,
                    )
                await self._write_status(
                    envelope,
                    operation=operation,
                    status=TaskStatus.RUNNING,
                    result=result,
                )
                return FinalizeResult(
                    task_id=envelope.task_id,
                    status=TaskStatus.RUNNING.value,
                    result_topic="",
                )
            if not state.complete:
                await self._write_status(
                    envelope,
                    operation=operation,
                    status=TaskStatus.RUNNING,
                    result=result,
                )
                return FinalizeResult(
                    task_id=envelope.task_id,
                    status=TaskStatus.RUNNING.value,
                    result_topic="",
                )
            status = TaskStatus.FAILED if state.failed else TaskStatus.COMPLETED
            result = _aggregate_helper_results(state.helper_results)
        await self._write_status(
            envelope,
            operation=operation,
            status=status,
            result=result,
            ttl_seconds=self._settings.completed_ttl_seconds,
        )
        if status == TaskStatus.FAILED:
            await self._publish_dead_letter(
                envelope,
                operation=operation,
                result=result,
                payload=payload,
            )
        final = MessageEnvelope.create(
            producer=self._settings.service_name,
            message_type=MessageType.TASK_RESULT,
            data_type=envelope.data_type,
            task_id=envelope.task_id,
            correlation_id=envelope.correlation_id,
            payload=TaskResultPayload(
                operation=operation,
                status=status,
                result=result,
                source_message_id=envelope.message_id,
            ).to_payload(),
        )
        await self._producer.publish(
            self._settings.task_result_topic,
            final,
            key=envelope.task_id,
        )
        if self._state_repository is not None:
            await self._state_repository.mark_final_published(
                envelope.task_id,
                status=str(status),
                result=result,
            )
        return FinalizeResult(
            task_id=envelope.task_id,
            status=status,
            result_topic=self._settings.task_result_topic,
        )

    async def _publish_task_started(self, envelope: MessageEnvelope, *, operation: str) -> None:
        started = MessageEnvelope.create(
            producer=self._settings.service_name,
            message_type=MessageType.TASK_STARTED,
            data_type=envelope.data_type,
            task_id=envelope.task_id,
            correlation_id=envelope.correlation_id,
            payload=TaskStartedPayload(
                operation=operation,
                status=TaskStatus.RUNNING,
                source_message_id=envelope.message_id,
            ).to_payload(),
        )
        await self._producer.publish(
            self._settings.task_started_topic,
            started,
            key=envelope.task_id,
        )

    async def _publish_domain_command(
        self,
        envelope: MessageEnvelope,
        *,
        payload: TaskIntakePayload,
        topic: str,
    ) -> None:
        command = MessageEnvelope.create(
            producer=self._settings.service_name,
            message_type=MessageType.DOMAIN_COMMAND,
            data_type=envelope.data_type,
            task_id=envelope.task_id,
            correlation_id=envelope.correlation_id,
            payload=DomainCommandPayload(
                operation=payload.operation,
                request=payload.request,
                context=payload.context,
                source_message_id=envelope.message_id,
            ).to_payload(),
        )
        await self._producer.publish(topic, command, key=envelope.task_id)

    async def _publish_helper_command_from_plan(
        self,
        envelope: MessageEnvelope,
        *,
        operation: str,
        plan: dict[str, Any],
        topic: str,
        attempt: int = 1,
        source_message_id: str | None = None,
    ) -> None:
        command = MessageEnvelope.create(
            producer=self._settings.service_name,
            message_type=MessageType.HELPER_COMMAND,
            data_type=envelope.data_type,
            task_id=envelope.task_id,
            correlation_id=envelope.correlation_id,
            payload=HelperCommandPayload(
                operation=operation,
                helper=topic,
                plan=plan,
                source_message_id=source_message_id or envelope.message_id,
            ).to_payload()
            | {"attempt": attempt},
        )
        await self._producer.publish(topic, command, key=envelope.task_id)

    async def _publish_helper_command(
        self,
        envelope: MessageEnvelope,
        *,
        payload: DomainResultPayload,
        topic: str,
    ) -> None:
        command = MessageEnvelope.create(
            producer=self._settings.service_name,
            message_type=MessageType.HELPER_COMMAND,
            data_type=envelope.data_type,
            task_id=envelope.task_id,
            correlation_id=envelope.correlation_id,
            payload=HelperCommandPayload(
                operation=payload.operation,
                helper=topic,
                plan=payload.plan,
                source_message_id=envelope.message_id,
            ).to_payload()
            | {"attempt": 1},
        )
        await self._producer.publish(topic, command, key=envelope.task_id)

    async def _publish_dead_letter(
        self,
        envelope: MessageEnvelope,
        *,
        operation: str,
        result: dict[str, Any],
        payload: HelperResultPayload,
    ) -> None:
        dead_letter = MessageEnvelope.create(
            producer=self._settings.service_name,
            message_type=MessageType.TASK_STEP,
            data_type=envelope.data_type,
            task_id=envelope.task_id,
            correlation_id=envelope.correlation_id,
            payload=DeadLetterPayload(
                operation=operation,
                status=TaskStatus.FAILED,
                source_topic=payload.helper,
                source_message_id=payload.source_message_id,
                failed_message_id=envelope.message_id,
                attempt=payload.attempt,
                retryable=payload.retryable,
                error=str(result.get("error", payload.error)),
                result=result,
                context={"helper": payload.helper},
            ).to_payload(),
        )
        await self._producer.publish(
            self._settings.dead_letter_topic,
            dead_letter,
            key=envelope.task_id,
        )

    async def _write_status(
        self,
        envelope: MessageEnvelope,
        *,
        operation: str,
        status: str | TaskStatus,
        result: dict[str, Any] | None = None,
        ttl_seconds: int | None = None,
    ) -> None:
        if self._status_store is None:
            return
        await self._status_store.set_status(
            TaskStatusRecord(
                task_id=envelope.task_id,
                status=str(status),
                correlation_id=envelope.correlation_id,
                data_type=envelope.data_type,
                operation=operation,
                result=dict(result or {}),
            ),
            ttl_seconds=ttl_seconds,
        )


def _helper_topics(operation: str) -> tuple[str, ...]:
    if operation == "ingest":
        return (TOPICS.helper_ingestion_commands,)
    if operation == "search":
        return (TOPICS.helper_retrieval_commands,)
    if operation == "delete":
        return (TOPICS.helper_retrieval_commands, TOPICS.helper_storage_commands)
    raise ValueError(f"unsupported helper dispatch operation: {operation}")


def _aggregate_helper_results(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if len(results) == 1:
        return dict(next(iter(results.values())))
    return {"helpers": {helper: dict(result) for helper, result in sorted(results.items())}}


def _index_plan_from_ingestion_result(
    operation: str,
    helper: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    if operation != "ingest" or helper != TOPICS.helper_ingestion_commands:
        return {}
    for key in ("index_request", "retrieval_index", "retrieval_index_request"):
        value = result.get(key)
        if isinstance(value, dict):
            return dict(value)
    if isinstance(result.get("collection_name"), str) and isinstance(result.get("chunks"), list):
        return {
            key: result[key]
            for key in ("collection_name", "chunks", "payloads", "retrieval_config")
            if key in result
        }
    return {}


def _followup_plans_from_ingestion_result(
    operation: str,
    helper: str,
    result: dict[str, Any],
) -> tuple[tuple[str, dict[str, Any]], ...]:
    if operation != "ingest" or helper != TOPICS.helper_ingestion_commands:
        return ()
    followups: list[tuple[str, dict[str, Any]]] = []
    storage_plan = _storage_plan_from_ingestion_result(result)
    if storage_plan:
        followups.append((TOPICS.helper_storage_commands, storage_plan))
    index_plan = _index_plan_from_ingestion_result(operation, helper, result)
    if index_plan:
        followups.append((TOPICS.helper_retrieval_index_commands, index_plan))
    return tuple(followups)


def _storage_plan_from_ingestion_result(result: dict[str, Any]) -> dict[str, Any]:
    for key in ("storage_request", "raw_storage", "raw_storage_request"):
        value = result.get(key)
        if isinstance(value, dict):
            plan = dict(value)
            plan.setdefault("operation", "put")
            return plan
    return {}


def _result_with_failure_metadata(
    result: dict[str, Any],
    payload: DomainResultPayload | HelperResultPayload,
) -> dict[str, Any]:
    enriched = dict(result)
    if payload.error:
        enriched.setdefault("ok", False)
        enriched.setdefault("error", payload.error)
    if enriched.get("ok") is False:
        enriched.setdefault("attempt", payload.attempt)
        enriched.setdefault("retryable", payload.retryable)
    return enriched


def _should_retry(payload: HelperResultPayload, max_attempts: int) -> bool:
    return bool(payload.retryable and payload.attempt < max_attempts)


def _retry_plan(
    state: Any,
    helper: str,
    *,
    fallback_operation: str,
) -> RetryPlan:
    if state is None:
        return RetryPlan(operation=fallback_operation, plan={})
    stored = state.helper_plans.get(helper, {})
    operation = str(stored.get("operation") or fallback_operation)
    plan_value = stored.get("plan", {})
    plan = dict(plan_value if isinstance(plan_value, dict) else {})
    return RetryPlan(operation=operation, plan=plan)
