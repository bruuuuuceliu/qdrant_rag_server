"""Manager service settings."""

from __future__ import annotations

from dataclasses import dataclass

from configs.config import get_int_value, get_value


@dataclass(frozen=True, slots=True)
class ManagerSettings:
    service_name: str = "manager_service"
    ingest_topic: str = "ingestion.requests"
    workflow_topic: str = "workflow.events"
    local_queue_maxsize: int = 1000


def load_manager_settings(values: dict[str, str]) -> ManagerSettings:
    return ManagerSettings(
        service_name=get_value(values, "MANAGER_SERVICE_NAME", "manager_service"),
        ingest_topic=get_value(values, "MANAGER_INGEST_TOPIC", "ingestion.requests"),
        workflow_topic=get_value(values, "MANAGER_WORKFLOW_TOPIC", "workflow.events"),
        local_queue_maxsize=get_int_value(values, "MANAGER_LOCAL_QUEUE_MAXSIZE", 1000),
    )
