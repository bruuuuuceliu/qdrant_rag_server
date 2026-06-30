"""Task manager service settings."""

from __future__ import annotations

from dataclasses import dataclass

from shared.contracts import TOPICS


@dataclass(frozen=True, slots=True)
class TaskManagerSettings:
    service_name: str = "task_manager_service"
    task_intake_topic: str = TOPICS.task_intake
    task_request_topic: str = TOPICS.task_requests
    task_event_topic: str = TOPICS.task_events
    task_result_topic: str = TOPICS.task_results
    redis_status_url: str = "redis://127.0.0.1:6379/0"
    redis_key_prefix: str = "task:"
    completed_ttl_seconds: int = 86400

    @classmethod
    def from_values(cls, values: dict[str, str]) -> TaskManagerSettings:
        return cls(
            service_name=values.get("TASK_MANAGER_SERVICE_NAME", "task_manager_service"),
            task_intake_topic=values.get("TASK_MANAGER_TASK_INTAKE_TOPIC", TOPICS.task_intake),
            task_request_topic=values.get("TASK_MANAGER_TASK_REQUEST_TOPIC", TOPICS.task_requests),
            task_event_topic=values.get("TASK_MANAGER_TASK_EVENT_TOPIC", TOPICS.task_events),
            task_result_topic=values.get("TASK_MANAGER_TASK_RESULT_TOPIC", TOPICS.task_results),
            redis_status_url=values.get("REDIS_TASK_STATUS_URL", "redis://127.0.0.1:6379/0"),
            redis_key_prefix=values.get("REDIS_TASK_STATUS_KEY_PREFIX", "task:"),
            completed_ttl_seconds=int(values.get("REDIS_TASK_COMPLETED_TTL_SECONDS", "86400")),
        )


@dataclass(frozen=True, slots=True)
class TaskManagerHealth:
    service: str
    broker_connected: bool
    redis_connected: bool

    @property
    def ready(self) -> bool:
        return self.broker_connected and self.redis_connected
