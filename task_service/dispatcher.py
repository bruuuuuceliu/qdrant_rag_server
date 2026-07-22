"""Task service orchestration core."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import logging
from typing import Any

from shared.contracts import (
    DeadLetterPayload,
    HelperCommandPayload,
    HelperResultPayload,
    MessageConsumer,
    MessageEnvelope,
    MessageProducer,
    MessageType,
    ProjectPlanRequestPayload,
    ProjectPlanResultPayload,
    TOPICS,
    TaskEventPayload,
    TaskExecutionResultPayload,
    TaskRequestPayload,
    TaskStatus,
)
from task_service.config import TaskServiceSettings
from task_service.repository import PendingHelperDispatch, TaskStateRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DispatchResult:
    task_id: str
    data_type: str
    operation: str
    project_plan_topic: str


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
class RecoveryResult:
    recovered: int


@dataclass(frozen=True, slots=True)
class RetryPlan:
    operation: str
    plan: dict[str, Any]


class TaskServiceDispatcher:
    """Consumes task requests and owns planning/helper orchestration."""

    def __init__(
        self,
        *,
        producer: MessageProducer,
        state_repository: TaskStateRepository | None = None,
        settings: TaskServiceSettings | None = None,
    ) -> None:
        self._producer = producer
        self._state_repository = state_repository
        self._settings = settings or TaskServiceSettings()

    @property
    def recovery_supported(self) -> bool:
        return hasattr(self._state_repository, "claim_due_helper_dispatches")

    async def dispatch_task_request(self, envelope: MessageEnvelope) -> DispatchResult:
        payload = TaskRequestPayload.from_envelope(envelope)
        operation = payload.operation
        await self._record_execution(envelope, operation=operation)
        logger.info(
            "task service dispatch request task_id=%s operation=%s data_type=%s project_plan_topic=%s",
            envelope.task_id,
            operation,
            envelope.data_type,
            self._settings.project_plan_request_topic,
        )
        await self._publish_task_event(
            envelope,
            operation=operation,
            status=TaskStatus.RUNNING,
            event="task.running",
            source_message_id=envelope.message_id,
        )
        await self._publish_project_plan_request(envelope, payload=payload)
        return DispatchResult(
            task_id=envelope.task_id,
            data_type=envelope.data_type,
            operation=operation,
            project_plan_topic=self._settings.project_plan_request_topic,
        )

    async def run_once(self, consumer: MessageConsumer) -> DispatchResult:
        envelope = await consumer.consume(self._settings.task_request_topic)
        return await self.dispatch_task_request(envelope)

    async def dispatch_project_plan_result(self, envelope: MessageEnvelope) -> HelperDispatchResult:
        payload = ProjectPlanResultPayload.from_envelope(envelope)
        await self._record_execution(envelope, operation=payload.operation)
        if envelope.data_type == "workflow_log":
            final = await self.finalize_project_plan_result(envelope)
            return HelperDispatchResult(
                task_id=final.task_id,
                operation=payload.operation,
                helper_topics=(),
            )
        operation = payload.operation
        helper_topics = _helper_topics(operation)
        logger.info(
            "task service dispatch project_plan_result task_id=%s operation=%s data_type=%s helper_topics=%s",
            envelope.task_id,
            operation,
            envelope.data_type,
            ",".join(helper_topics),
        )
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
            command = await self._publish_helper_command(envelope, payload=payload, topic=topic)
            if self._state_repository is not None:
                await self._record_helper_dispatch(
                    envelope.task_id,
                    topic,
                    attempt=1,
                    source_message_id=command.message_id,
                )
        await self._publish_task_event(
            envelope,
            operation=operation,
            status=TaskStatus.DISPATCHED,
            event="task.dispatched",
            source_message_id=envelope.message_id,
        )
        return HelperDispatchResult(
            task_id=envelope.task_id,
            operation=operation,
            helper_topics=helper_topics,
        )

    async def finalize_project_plan_result(self, envelope: MessageEnvelope) -> FinalizeResult:
        payload = ProjectPlanResultPayload.from_envelope(envelope)
        await self._record_execution(envelope, operation=payload.operation)
        result = _result_with_failure_metadata(payload.result, payload)
        status = TaskStatus.COMPLETED if result.get("ok", True) is not False else TaskStatus.FAILED
        logger.info(
            "task service finalize project_plan_result task_id=%s operation=%s status=%s result_topic=%s",
            envelope.task_id,
            payload.operation,
            str(status),
            self._settings.task_result_topic,
        )
        await self._publish_task_event(
            envelope,
            operation=payload.operation,
            status=status,
            event="task.completed" if status == TaskStatus.COMPLETED else "task.failed",
            result=result,
            source_message_id=envelope.message_id,
        )
        await self._publish_task_result(
            envelope,
            operation=payload.operation,
            status=status,
            result=result,
            source_message_id=envelope.message_id,
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

    async def finalize_helper_result(self, envelope: MessageEnvelope) -> FinalizeResult:
        payload = HelperResultPayload.from_envelope(envelope)
        operation = payload.operation
        await self._record_execution(envelope, operation=operation)
        result = _result_with_failure_metadata(payload.result, payload)
        status = TaskStatus.COMPLETED if result.get("ok", True) is not False else TaskStatus.FAILED
        helper = payload.helper
        logger.info(
            "task service handle helper_result task_id=%s operation=%s helper=%s status=%s attempt=%s",
            envelope.task_id,
            operation,
            helper,
            str(status),
            payload.attempt,
        )
        if self._state_repository is not None:
            existing = await self._state_repository.get(envelope.task_id)
            if existing is not None and existing.final_published:
                logger.info(
                    "task service skip duplicate final task_id=%s helper=%s final_status=%s",
                    envelope.task_id,
                    helper,
                    existing.final_status,
                )
                return FinalizeResult(
                    task_id=envelope.task_id,
                    status=existing.final_status,
                    result_topic="",
                )
            existing_complete = existing is not None and existing.complete
            if existing_complete:
                status = TaskStatus.FAILED if existing.failed else TaskStatus.COMPLETED
                result = _aggregate_helper_results(existing.helper_results)
            elif _has_recorded_helper_result(existing, helper, envelope.message_id):
                logger.info(
                    "task service skip duplicate helper_result task_id=%s helper=%s message_id=%s",
                    envelope.task_id,
                    helper,
                    envelope.message_id,
                )
                return FinalizeResult(
                    task_id=envelope.task_id,
                    status=TaskStatus.RUNNING.value,
                    result_topic="",
                )
            if not existing_complete and _should_retry(payload, self._settings.max_attempts):
                retry_plan = _retry_plan(existing, helper, fallback_operation=operation)
                next_attempt_at = (
                    _utc_timestamp(self._settings.retry_backoff_seconds)
                    if self._settings.retry_backoff_seconds > 0
                    else ""
                )
                logger.info(
                    "task service retry helper task_id=%s helper=%s next_attempt=%s next_attempt_at=%s",
                    envelope.task_id,
                    helper,
                    payload.attempt + 1,
                    next_attempt_at,
                )
                await self._state_repository.record_helper_attempt(
                    envelope.task_id,
                    helper,
                    attempt=payload.attempt,
                    status="retrying",
                    result=result,
                    retryable=payload.retryable,
                    error=str(result.get("error", payload.error)),
                    source_message_id=payload.source_message_id,
                    failed_message_id=envelope.message_id,
                    next_attempt_at=next_attempt_at,
                )
                if next_attempt_at:
                    await self._publish_task_event(
                        envelope,
                        operation=operation,
                        status=TaskStatus.RUNNING,
                        event="task.retry_scheduled",
                        result=result,
                        source_message_id=envelope.message_id,
                        context={
                            "helper": helper,
                            "attempt": payload.attempt + 1,
                            "next_attempt_at": next_attempt_at,
                        },
                    )
                    return FinalizeResult(
                        task_id=envelope.task_id,
                        status=TaskStatus.RUNNING.value,
                        result_topic="",
                    )
                retry_command = await self._publish_helper_command_from_plan(
                    envelope,
                    operation=retry_plan.operation,
                    plan=retry_plan.plan,
                    topic=helper,
                    attempt=payload.attempt + 1,
                    source_message_id=payload.source_message_id or envelope.message_id,
                )
                await self._record_helper_dispatch(
                    envelope.task_id,
                    helper,
                    attempt=payload.attempt + 1,
                    source_message_id=retry_command.message_id,
                )
                await self._publish_task_event(
                    envelope,
                    operation=operation,
                    status=TaskStatus.RUNNING,
                    event="task.retrying",
                    result=result,
                    source_message_id=envelope.message_id,
                    context={"helper": helper, "attempt": payload.attempt + 1},
                )
                return FinalizeResult(
                    task_id=envelope.task_id,
                    status=TaskStatus.RUNNING.value,
                    result_topic="",
                )
            if not existing_complete:
                state = await self._state_repository.mark_helper_result(
                    envelope.task_id,
                    helper,
                    ok=status == TaskStatus.COMPLETED,
                    result=result,
                    attempt=payload.attempt,
                    retryable=payload.retryable,
                    error=str(result.get("error", payload.error)),
                    source_message_id=payload.source_message_id,
                    failed_message_id=envelope.message_id,
                )
                followups = _followup_plans_from_ingestion_result(operation, helper, result)
                if status == TaskStatus.COMPLETED and followups:
                    logger.info(
                        "task service schedule followups task_id=%s helper=%s followup_topics=%s",
                        envelope.task_id,
                        helper,
                        ",".join(topic for topic, _plan in followups),
                    )
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
                        command = await self._publish_helper_command_from_plan(
                            envelope,
                            operation=str(plan.get("operation") or operation),
                            plan=plan,
                            topic=topic,
                        )
                        await self._record_helper_dispatch(
                            envelope.task_id,
                            topic,
                            attempt=1,
                            source_message_id=command.message_id,
                        )
                    await self._publish_task_event(
                        envelope,
                        operation=operation,
                        status=TaskStatus.RUNNING,
                        event="task.followups_dispatched",
                        result=result,
                        source_message_id=envelope.message_id,
                        context={"helper": helper},
                    )
                    return FinalizeResult(
                        task_id=envelope.task_id,
                        status=TaskStatus.RUNNING.value,
                        result_topic="",
                    )
                if not state.complete:
                    logger.info(
                        "task service waiting helpers task_id=%s completed=%s expected=%s failed=%s",
                        envelope.task_id,
                        ",".join(sorted(state.completed_helpers)),
                        ",".join(sorted(state.expected_helpers)),
                        ",".join(sorted(state.failed_helpers)),
                    )
                    await self._publish_task_event(
                        envelope,
                        operation=operation,
                        status=TaskStatus.RUNNING,
                        event="task.waiting_helpers",
                        result=result,
                        source_message_id=envelope.message_id,
                        context={"helper": helper},
                    )
                    return FinalizeResult(
                        task_id=envelope.task_id,
                        status=TaskStatus.RUNNING.value,
                        result_topic="",
                    )
                status = TaskStatus.FAILED if state.failed else TaskStatus.COMPLETED
                result = _aggregate_helper_results(state.helper_results)
        logger.info(
            "task service finalize helpers task_id=%s operation=%s status=%s result_topic=%s",
            envelope.task_id,
            operation,
            str(status),
            self._settings.task_result_topic,
        )
        if status == TaskStatus.FAILED:
            logger.info(
                "task service publish dead_letter task_id=%s helper=%s topic=%s",
                envelope.task_id,
                payload.helper,
                self._settings.dead_letter_topic,
            )
            await self._publish_dead_letter(
                envelope,
                operation=operation,
                result=result,
                payload=payload,
            )
        await self._publish_task_event(
            envelope,
            operation=operation,
            status=status,
            event="task.completed" if status == TaskStatus.COMPLETED else "task.failed",
            result=result,
            source_message_id=envelope.message_id,
        )
        await self._publish_task_result(
            envelope,
            operation=operation,
            status=status,
            result=result,
            source_message_id=envelope.message_id,
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

    async def recover_due_helpers(
        self,
        *,
        now: str | None = None,
        limit: int | None = None,
    ) -> RecoveryResult:
        claim_due = getattr(self._state_repository, "claim_due_helper_dispatches", None)
        if claim_due is None:
            return RecoveryResult(recovered=0)
        now = now or _utc_timestamp()
        steps = await claim_due(
            now=now,
            lease_owner=self._settings.service_name,
            lease_expires_at=_utc_timestamp(self._settings.helper_lease_seconds),
            max_attempts=self._settings.max_attempts,
            limit=limit or self._settings.recovery_batch_size,
        )
        recovered = 0
        for step in steps:
            if step.reason == "expired_lease_terminal":
                await self._publish_expired_helper_failure(step)
            else:
                await self._redispatch_recovered_helper(step)
            recovered += 1
        return RecoveryResult(recovered=recovered)

    async def _redispatch_recovered_helper(self, step: PendingHelperDispatch) -> None:
        envelope = _recovery_envelope(step, producer=self._settings.service_name)
        next_attempt = step.attempt + 1
        command = await self._publish_helper_command_from_plan(
            envelope,
            operation=step.operation,
            plan=step.plan,
            topic=step.helper,
            attempt=next_attempt,
            source_message_id=step.last_source_message_id or envelope.message_id,
        )
        await self._record_helper_dispatch(
            step.task_id,
            step.helper,
            attempt=next_attempt,
            source_message_id=command.message_id,
        )
        await self._publish_task_event(
            envelope,
            operation=step.operation,
            status=TaskStatus.RUNNING,
            event="task.helper_recovered",
            source_message_id=command.message_id,
            context={
                "helper": step.helper,
                "attempt": next_attempt,
                "reason": step.reason,
            },
        )

    async def _publish_expired_helper_failure(self, step: PendingHelperDispatch) -> None:
        result = {
            "ok": False,
            "error": "helper lease expired",
            "attempt": step.attempt,
            "retryable": False,
        }
        envelope = MessageEnvelope.create(
            producer=self._settings.service_name,
            message_type=MessageType.HELPER_RESULT,
            data_type=step.data_type,
            task_id=step.task_id,
            correlation_id=step.correlation_id,
            payload=HelperResultPayload(
                operation=step.operation,
                helper=step.helper,
                result=result,
                attempt=step.attempt,
                retryable=False,
                error="helper lease expired",
                source_message_id=step.last_source_message_id,
            ).to_payload(),
        )
        await self.finalize_helper_result(envelope)

    async def _record_execution(self, envelope: MessageEnvelope, *, operation: str) -> None:
        if self._state_repository is None:
            return
        record = getattr(self._state_repository, "record_execution", None)
        if record is None:
            return
        await record(
            envelope.task_id,
            data_type=envelope.data_type,
            correlation_id=envelope.correlation_id,
            operation=operation,
        )

    async def _record_helper_dispatch(
        self,
        task_id: str,
        helper: str,
        *,
        attempt: int,
        source_message_id: str,
    ) -> None:
        if self._state_repository is None:
            return
        await self._state_repository.record_helper_dispatch(
            task_id,
            helper,
            attempt=attempt,
            source_message_id=source_message_id,
            lease_owner=self._settings.service_name,
            lease_expires_at=_utc_timestamp(self._settings.helper_lease_seconds),
        )

    async def _publish_task_event(
        self,
        envelope: MessageEnvelope,
        *,
        operation: str,
        status: str | TaskStatus,
        event: str,
        result: dict[str, Any] | None = None,
        error: str = "",
        source_message_id: str = "",
        context: dict[str, Any] | None = None,
    ) -> None:
        task_event = MessageEnvelope.create(
            producer=self._settings.service_name,
            message_type=MessageType.TASK_EVENT,
            data_type=envelope.data_type,
            task_id=envelope.task_id,
            correlation_id=envelope.correlation_id,
            payload=TaskEventPayload(
                operation=operation,
                status=str(status),
                event=event,
                result=dict(result or {}),
                error=error,
                source_message_id=source_message_id,
                context=dict(context or {}),
            ).to_payload(),
        )
        await self._producer.publish(
            self._settings.task_event_topic,
            task_event,
            key=envelope.task_id,
        )
        logger.info(
            "task service publish event task_id=%s operation=%s status=%s topic=%s",
            envelope.task_id,
            operation,
            str(status),
            self._settings.task_event_topic,
        )

    async def _publish_project_plan_request(
        self,
        envelope: MessageEnvelope,
        *,
        payload: TaskRequestPayload,
    ) -> None:
        request = MessageEnvelope.create(
            producer=self._settings.service_name,
            message_type=MessageType.PROJECT_PLAN_REQUEST,
            data_type=envelope.data_type,
            task_id=envelope.task_id,
            correlation_id=envelope.correlation_id,
            payload=ProjectPlanRequestPayload(
                operation=payload.operation,
                request=payload.request,
                context=payload.context,
                source_message_id=payload.source_message_id or envelope.message_id,
            ).to_payload(),
        )
        await self._producer.publish(
            self._settings.project_plan_request_topic,
            request,
            key=envelope.task_id,
        )
        logger.info(
            "task service publish project_plan_request task_id=%s operation=%s topic=%s",
            envelope.task_id,
            payload.operation,
            self._settings.project_plan_request_topic,
        )

    async def _publish_helper_command_from_plan(
        self,
        envelope: MessageEnvelope,
        *,
        operation: str,
        plan: dict[str, Any],
        topic: str,
        attempt: int = 1,
        source_message_id: str | None = None,
    ) -> MessageEnvelope:
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
                attempt=attempt,
                source_message_id=source_message_id or envelope.message_id,
            ).to_payload(),
        )
        await self._producer.publish(topic, command, key=envelope.task_id)
        logger.info(
            "task service publish helper_command task_id=%s operation=%s topic=%s attempt=%s",
            envelope.task_id,
            operation,
            topic,
            attempt,
        )
        return command

    async def _publish_helper_command(
        self,
        envelope: MessageEnvelope,
        *,
        payload: ProjectPlanResultPayload,
        topic: str,
    ) -> MessageEnvelope:
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
                attempt=1,
                source_message_id=envelope.message_id,
            ).to_payload(),
        )
        await self._producer.publish(topic, command, key=envelope.task_id)
        logger.info(
            "task service publish helper_command task_id=%s operation=%s topic=%s attempt=1",
            envelope.task_id,
            payload.operation,
            topic,
        )
        return command

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
        logger.info(
            "task service publish dead_letter task_id=%s topic=%s source_topic=%s",
            envelope.task_id,
            self._settings.dead_letter_topic,
            payload.helper,
        )

    async def _publish_task_result(
        self,
        envelope: MessageEnvelope,
        *,
        operation: str,
        status: str | TaskStatus,
        result: dict[str, Any],
        source_message_id: str,
    ) -> None:
        final = MessageEnvelope.create(
            producer=self._settings.service_name,
            message_type=MessageType.TASK_RESULT,
            data_type=envelope.data_type,
            task_id=envelope.task_id,
            correlation_id=envelope.correlation_id,
            payload=TaskExecutionResultPayload(
                operation=operation,
                status=str(status),
                result=result,
                source_message_id=source_message_id,
            ).to_payload(),
        )
        await self._producer.publish(
            self._settings.task_result_topic,
            final,
            key=envelope.task_id,
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
    payload: ProjectPlanResultPayload | HelperResultPayload,
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


def _retry_plan(state: Any, helper: str, *, fallback_operation: str) -> RetryPlan:
    if state is not None:
        stored = state.helper_plans.get(helper, {})
        if isinstance(stored, dict):
            return RetryPlan(
                operation=str(stored.get("operation") or fallback_operation),
                plan=dict(stored.get("plan") if isinstance(stored.get("plan"), dict) else {}),
            )
    return RetryPlan(operation=fallback_operation, plan={})


def _has_recorded_helper_result(state: Any, helper: str, failed_message_id: str) -> bool:
    if state is None or not failed_message_id:
        return False
    for attempt in state.helper_attempts.get(helper, []):
        if (
            attempt.get("event") == "result"
            and attempt.get("failed_message_id") == failed_message_id
        ):
            return True
    return False


def _recovery_envelope(step: PendingHelperDispatch, *, producer: str) -> MessageEnvelope:
    return MessageEnvelope.create(
        producer=producer,
        message_type=MessageType.TASK_STEP,
        data_type=step.data_type,
        task_id=step.task_id,
        correlation_id=step.correlation_id,
        payload={
            "operation": step.operation,
            "status": TaskStatus.RUNNING.value,
            "event": "task.recovery",
            "context": {"helper": step.helper, "reason": step.reason},
        },
    )


def _utc_timestamp(offset_seconds: int | float = 0) -> str:
    value = datetime.now(UTC) + timedelta(seconds=float(offset_seconds))
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")
