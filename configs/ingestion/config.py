"""Ingestion service settings."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from configs.config import get_bool_value, get_int_value, get_value
from shared.contracts import TOPICS


@dataclass(frozen=True, slots=True)
class IngestionSettings:
    enabled: bool = True
    service_name: str = "ingestion_service"
    command_topic: str = TOPICS.helper_ingestion_commands
    worker_count: int = 4
    queue_maxsize: int = 100
    job_db_path: Path = Path("/var/lib/rag/ingestion_jobs.db")


def load_ingestion_settings(values: dict[str, str]) -> IngestionSettings:
    return IngestionSettings(
        enabled=get_bool_value(values, "INGESTION_SERVICE_ENABLED", True),
        service_name=get_value(values, "INGESTION_SERVICE_NAME", "ingestion_service"),
        command_topic=get_value(
            values,
            "INGESTION_HELPER_COMMAND_TOPIC",
            TOPICS.helper_ingestion_commands,
        ),
        worker_count=get_int_value(values, "INGESTION_WORKER_COUNT", 4),
        queue_maxsize=get_int_value(values, "INGESTION_QUEUE_MAXSIZE", 100),
        job_db_path=Path(
            get_value(values, "INGESTION_JOB_DB_PATH", "/var/lib/rag/ingestion_jobs.db")
        ),
    )
