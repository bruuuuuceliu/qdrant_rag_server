"""Task orchestration service settings."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from shared.contracts import TOPICS


@dataclass(frozen=True, slots=True)
class TaskServiceSettings:
    service_name: str = "task_service"
    task_request_topic: str = TOPICS.task_requests
    project_plan_request_topic: str = TOPICS.project_plan_requests
    project_plan_result_topic: str = TOPICS.project_plan_results
    task_event_topic: str = TOPICS.task_events
    task_result_topic: str = TOPICS.task_results
    dead_letter_topic: str = TOPICS.task_dead_letters
    state_db_path: str = "examples/local/.data/task_service_state.db"
    max_attempts: int = 3
    helper_lease_seconds: int = 300
    retry_backoff_seconds: int = 0
    recovery_enabled: bool = True
    recovery_poll_seconds: float = 2.0
    recovery_batch_size: int = 25

    @classmethod
    def from_values(cls, values: dict[str, str]) -> "TaskServiceSettings":
        return cls(
            service_name=values.get("TASK_SERVICE_NAME", "task_service"),
            task_request_topic=values.get("TASK_SERVICE_TASK_REQUEST_TOPIC", TOPICS.task_requests),
            project_plan_request_topic=values.get(
                "TASK_SERVICE_PROJECT_PLAN_REQUEST_TOPIC",
                TOPICS.project_plan_requests,
            ),
            project_plan_result_topic=values.get(
                "TASK_SERVICE_PROJECT_PLAN_RESULT_TOPIC",
                TOPICS.project_plan_results,
            ),
            task_event_topic=values.get("TASK_SERVICE_TASK_EVENT_TOPIC", TOPICS.task_events),
            task_result_topic=values.get("TASK_SERVICE_TASK_RESULT_TOPIC", TOPICS.task_results),
            dead_letter_topic=values.get("TASK_SERVICE_DEAD_LETTER_TOPIC", TOPICS.task_dead_letters),
            state_db_path=values.get(
                "TASK_SERVICE_STATE_DB_PATH",
                str(Path(values.get("RAG_LOCAL_DATA_DIR", "examples/local/.data")) / "task_service_state.db"),
            ),
            max_attempts=int(values.get("TASK_SERVICE_MAX_ATTEMPTS", "3")),
            helper_lease_seconds=int(values.get("TASK_SERVICE_HELPER_LEASE_SECONDS", "300")),
            retry_backoff_seconds=int(values.get("TASK_SERVICE_RETRY_BACKOFF_SECONDS", "0")),
            recovery_enabled=_bool_value(values.get("TASK_SERVICE_RECOVERY_ENABLED", "true")),
            recovery_poll_seconds=float(values.get("TASK_SERVICE_RECOVERY_POLL_SECONDS", "2.0")),
            recovery_batch_size=int(values.get("TASK_SERVICE_RECOVERY_BATCH_SIZE", "25")),
        )


def _bool_value(value: str) -> bool:
    return value.strip().lower() not in {"0", "false", "no", "off"}
