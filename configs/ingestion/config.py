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
    request_topic: str = "ingestion.requests"
    command_topic: str = TOPICS.helper_ingestion_commands
    worker_count: int = 4
    queue_maxsize: int = 100
    job_db_path: Path = Path("/var/lib/rag/ingestion_jobs.db")
    retrieval_index_enabled: bool = True
    retrieval_index_topic: str = "retrieval.index.requests"
    retrieval_index_queue_broker: str = "sqlite"
    retrieval_index_queue_db_path: Path = Path("/var/lib/rag/ingestion_queue.db")
    retrieval_index_queue_maxsize: int = 100
    retrieval_index_response_timeout: float = 30.0


def load_ingestion_settings(values: dict[str, str]) -> IngestionSettings:
    return IngestionSettings(
        enabled=get_bool_value(values, "INGESTION_SERVICE_ENABLED", True),
        service_name=get_value(values, "INGESTION_SERVICE_NAME", "ingestion_service"),
        request_topic=get_value(values, "INGESTION_REQUEST_TOPIC", "ingestion.requests"),
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
        retrieval_index_enabled=get_bool_value(
            values,
            "INGESTION_RETRIEVAL_INDEX_ENABLED",
            True,
        ),
        retrieval_index_topic=get_value(
            values,
            "INGESTION_RETRIEVAL_INDEX_TOPIC",
            "retrieval.index.requests",
        ),
        retrieval_index_queue_broker=get_value(
            values,
            "INGESTION_RETRIEVAL_INDEX_QUEUE_BROKER",
            "sqlite",
        ),
        retrieval_index_queue_db_path=Path(
            get_value(
                values,
                "INGESTION_RETRIEVAL_INDEX_QUEUE_DB_PATH",
                "/var/lib/rag/ingestion_queue.db",
            )
        ),
        retrieval_index_queue_maxsize=get_int_value(
            values,
            "INGESTION_RETRIEVAL_INDEX_QUEUE_MAXSIZE",
            100,
        ),
        retrieval_index_response_timeout=float(
            get_value(values, "INGESTION_RETRIEVAL_INDEX_RESPONSE_TIMEOUT", "30.0")
        ),
    )
