"""Manager service settings."""

from __future__ import annotations

from dataclasses import dataclass

from configs.config import get_float_value, get_int_value, get_value
from shared.contracts import TOPICS


@dataclass(frozen=True, slots=True)
class ManagerSettings:
    service_name: str = "manager_service"
    ingest_topic: str = "ingestion.requests"
    workflow_topic: str = "workflow.events"
    local_queue_maxsize: int = 1000
    ingestion_worker_mode: str = "embedded"
    queue_broker: str = "local"
    queue_db_path: str = "/tmp/qdrant_rag/ingestion_queue.db"
    project_client_mode: str = "local"
    project_grpc_target: str = "localhost:50052"
    retrieval_client_mode: str = "local"
    retrieval_topic: str = "retrieval.api.requests"
    retrieval_response_timeout: float = 30.0
    retrieval_http_base_url: str = "http://127.0.0.1:8081"
    retrieval_http_timeout: float = 30.0
    task_intake_topic: str = TOPICS.task_intake
    task_status_url: str = "redis://127.0.0.1:6379/0"
    task_status_key_prefix: str = "task:"
    task_completed_ttl_seconds: int = 86400


def load_manager_settings(values: dict[str, str]) -> ManagerSettings:
    return ManagerSettings(
        service_name=get_value(values, "MANAGER_SERVICE_NAME", "manager_service"),
        ingest_topic=get_value(values, "MANAGER_INGEST_TOPIC", "ingestion.requests"),
        workflow_topic=get_value(values, "MANAGER_WORKFLOW_TOPIC", "workflow.events"),
        local_queue_maxsize=get_int_value(values, "MANAGER_LOCAL_QUEUE_MAXSIZE", 1000),
        ingestion_worker_mode=get_value(
            values,
            "MANAGER_INGESTION_WORKER_MODE",
            "embedded",
        ),
        queue_broker=get_value(values, "MANAGER_QUEUE_BROKER", "local"),
        queue_db_path=get_value(
            values,
            "MANAGER_QUEUE_DB_PATH",
            "/tmp/qdrant_rag/ingestion_queue.db",
        ),
        project_client_mode=get_value(values, "MANAGER_PROJECT_CLIENT_MODE", "local"),
        project_grpc_target=get_value(
            values,
            "MANAGER_PROJECT_GRPC_TARGET",
            "localhost:50052",
        ),
        retrieval_client_mode=get_value(
            values,
            "MANAGER_RETRIEVAL_CLIENT_MODE",
            "local",
        ),
        retrieval_topic=get_value(
            values,
            "MANAGER_RETRIEVAL_TOPIC",
            "retrieval.api.requests",
        ),
        retrieval_response_timeout=get_float_value(
            values,
            "MANAGER_RETRIEVAL_RESPONSE_TIMEOUT",
            30.0,
        ),
        retrieval_http_base_url=get_value(
            values,
            "MANAGER_RETRIEVAL_HTTP_BASE_URL",
            "http://127.0.0.1:8081",
        ),
        retrieval_http_timeout=get_float_value(
            values,
            "MANAGER_RETRIEVAL_HTTP_TIMEOUT",
            30.0,
        ),
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
