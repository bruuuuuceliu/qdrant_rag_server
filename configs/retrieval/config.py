"""Retrieval component configuration helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from configs.config import get_bool_value, get_float_value, get_int_value, get_value
from shared.contracts import TOPICS


@dataclass(frozen=True, slots=True)
class RetrievalComponentSettings:
    bm25_sparse_vector_name: str
    bm25_dense_vector_name: str
    bm25_encoder_provider: str
    bm25_encoder_model: str
    bm25_text_field: str
    bm25_lemmatize: bool
    bm25_index_version: str
    ner_provider: str
    ner_model: str


@dataclass(frozen=True, slots=True)
class RetrievalHttpSettings:
    host: str
    port: int
    read_timeout: float


@dataclass(frozen=True, slots=True)
class RetrievalHelperSettings:
    service_name: str = "retrieval_service"
    command_topic: str = TOPICS.helper_retrieval_commands


@dataclass(frozen=True, slots=True)
class RetrievalIndexWorkerSettings:
    enabled: bool = True
    service_name: str = "retrieval_index_worker"
    request_topic: str = "retrieval.index.requests"
    command_topic: str = TOPICS.helper_retrieval_index_commands
    queue_broker: str = "sqlite"
    queue_db_path: Path = Path("/var/lib/rag/ingestion_queue.db")
    queue_maxsize: int = 100


@dataclass(frozen=True, slots=True)
class RetrievalPlacementSettings:
    enabled: bool = True
    db_path: Path = Path("/tmp/qdrant_rag/placement.db")
    routing_mode: str = "project_single"
    bucket_count: int = 1
    replication_factor: int = 1
    shard_id: str = "local-qdrant"
    cluster_id: str = "local"


def load_retrieval_component_settings(
    values: dict[str, str],
) -> RetrievalComponentSettings:
    return RetrievalComponentSettings(
        bm25_sparse_vector_name=get_value(values, "BM25_SPARSE_VECTOR_NAME", "bm25"),
        bm25_dense_vector_name=get_value(values, "BM25_DENSE_VECTOR_NAME", "dense"),
        bm25_encoder_provider=get_value(values, "BM25_ENCODER_PROVIDER", "fastembed"),
        bm25_encoder_model=get_value(values, "BM25_ENCODER_MODEL", "Qdrant/bm25"),
        bm25_text_field=get_value(values, "BM25_TEXT_FIELD", "text_lemmatized"),
        bm25_lemmatize=get_bool_value(values, "BM25_LEMMATIZE", True),
        bm25_index_version=get_value(values, "BM25_INDEX_VERSION", "qdrant_bm25_v1"),
        ner_provider=get_value(values, "RAG_NER_PROVIDER", "disabled"),
        ner_model=get_value(values, "RAG_NER_MODEL", "en_core_web_sm"),
    )


def load_retrieval_http_settings(values: dict[str, str]) -> RetrievalHttpSettings:
    return RetrievalHttpSettings(
        host=get_value(values, "RETRIEVAL_HTTP_HOST", "127.0.0.1"),
        port=get_int_value(values, "RETRIEVAL_HTTP_PORT", 8081),
        read_timeout=get_float_value(values, "RETRIEVAL_HTTP_READ_TIMEOUT", 5.0),
    )


def load_retrieval_helper_settings(values: dict[str, str]) -> RetrievalHelperSettings:
    return RetrievalHelperSettings(
        service_name=get_value(values, "RETRIEVAL_HELPER_SERVICE_NAME", "retrieval_service"),
        command_topic=get_value(
            values,
            "RETRIEVAL_HELPER_COMMAND_TOPIC",
            TOPICS.helper_retrieval_commands,
        ),
    )


def load_retrieval_index_worker_settings(
    values: dict[str, str],
) -> RetrievalIndexWorkerSettings:
    return RetrievalIndexWorkerSettings(
        enabled=get_bool_value(values, "RETRIEVAL_INDEX_WORKER_ENABLED", True),
        service_name=get_value(
            values,
            "RETRIEVAL_INDEX_WORKER_SERVICE_NAME",
            "retrieval_index_worker",
        ),
        request_topic=get_value(
            values,
            "RETRIEVAL_INDEX_REQUEST_TOPIC",
            "retrieval.index.requests",
        ),
        command_topic=get_value(
            values,
            "RETRIEVAL_INDEX_HELPER_COMMAND_TOPIC",
            TOPICS.helper_retrieval_index_commands,
        ),
        queue_broker=get_value(values, "RETRIEVAL_INDEX_QUEUE_BROKER", "sqlite"),
        queue_db_path=Path(
            get_value(
                values,
                "RETRIEVAL_INDEX_QUEUE_DB_PATH",
                "/var/lib/rag/ingestion_queue.db",
            )
        ),
        queue_maxsize=get_int_value(values, "RETRIEVAL_INDEX_QUEUE_MAXSIZE", 100),
    )


def load_retrieval_placement_settings(
    values: dict[str, str],
) -> RetrievalPlacementSettings:
    return RetrievalPlacementSettings(
        enabled=get_bool_value(values, "RETRIEVAL_PLACEMENT_ENABLED", True),
        db_path=Path(
            get_value(
                values,
                "RETRIEVAL_PLACEMENT_DB_PATH",
                "/tmp/qdrant_rag/placement.db",
            )
        ),
        routing_mode=get_value(
            values,
            "RETRIEVAL_PLACEMENT_ROUTING_MODE",
            "project_single",
        ),
        bucket_count=get_int_value(values, "RETRIEVAL_PLACEMENT_BUCKET_COUNT", 1),
        replication_factor=get_int_value(
            values,
            "RETRIEVAL_PLACEMENT_REPLICATION_FACTOR",
            1,
        ),
        shard_id=get_value(
            values,
            "RETRIEVAL_PLACEMENT_SHARD_ID",
            "local-qdrant",
        ),
        cluster_id=get_value(
            values,
            "RETRIEVAL_PLACEMENT_CLUSTER_ID",
            "local",
        ),
    )
