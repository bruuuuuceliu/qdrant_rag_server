"""Workflow log service settings."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from configs.config import get_bool_value, get_value


@dataclass(frozen=True, slots=True)
class WorkflowLogSettings:
    enabled: bool = True
    service_name: str = "workflow_log_service"
    topic: str = "ingestion.events"
    db_path: Path = Path("/var/lib/rag/workflow_log.db")


def load_workflow_log_settings(values: dict[str, str]) -> WorkflowLogSettings:
    return WorkflowLogSettings(
        enabled=get_bool_value(
            values,
            "WORKFLOW_LOG_SERVICE_ENABLED",
            True,
        ),
        service_name=get_value(
            values,
            "WORKFLOW_LOG_SERVICE_NAME",
            "workflow_log_service",
        ),
        topic=get_value(values, "WORKFLOW_LOG_TOPIC", "ingestion.events"),
        db_path=Path(
            get_value(values, "WORKFLOW_LOG_DB_PATH", "/var/lib/rag/workflow_log.db")
        ),
    )
