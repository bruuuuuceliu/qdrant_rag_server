"""Manager service settings."""

from __future__ import annotations

from dataclasses import dataclass

from configs.config import get_int_value, get_value
from shared.contracts import TOPICS


@dataclass(frozen=True, slots=True)
class ManagerSettings:
    service_name: str = "manager_service"
    task_intake_topic: str = TOPICS.task_intake
    task_status_url: str = "redis://127.0.0.1:6379/0"
    task_status_key_prefix: str = "task:"
    task_completed_ttl_seconds: int = 86400


def load_manager_settings(values: dict[str, str]) -> ManagerSettings:
    return ManagerSettings(
        service_name=get_value(values, "MANAGER_SERVICE_NAME", "manager_service"),
        task_intake_topic=get_value(
            values,
            "MANAGER_TASK_INTAKE_TOPIC",
            TOPICS.task_intake,
        ),
        task_status_url=get_value(
            values,
            "REDIS_TASK_STATUS_URL",
            "redis://127.0.0.1:6379/0",
        ),
        task_status_key_prefix=get_value(
            values,
            "REDIS_TASK_STATUS_KEY_PREFIX",
            "task:",
        ),
        task_completed_ttl_seconds=get_int_value(
            values,
            "REDIS_TASK_COMPLETED_TTL_SECONDS",
            86400,
        ),
    )
