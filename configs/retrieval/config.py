"""Retrieval component configuration helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from configs.config import get_bool_value, get_int_value, get_value
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
class RetrievalHelperSettings:
    service_name: str = "retrieval_service"
    command_topic: str = TOPICS.helper_retrieval_commands


@dataclass(frozen=True, slots=True)
class RetrievalIndexWorkerSettings:
    enabled: bool = True
    service_name: str = "retrieval_index_worker"
    command_topic: str = TOPICS.helper_retrieval_index_commands


def load_collection_index_config(values: dict[str, str]) -> Any:
    """Load the single default collection index (HNSW/optimizer) profile.

    Lazy-imports ``CollectionIndexConfig`` so config loading never requires the
    qdrant_client dependency. A single default profile is applied to every
    collection at creation time (see C4 design).
    """
    from retrieval_service.services.vector_store import CollectionIndexConfig

    return CollectionIndexConfig(
        hnsw_m=get_int_value(values, "RAG_QDRANT_HNSW_M", 16),
        hnsw_ef_construct=get_int_value(values, "RAG_QDRANT_HNSW_EF_CONSTRUCT", 100),
        full_scan_threshold=get_int_value(
            values,
            "RAG_QDRANT_FULL_SCAN_THRESHOLD",
            10000,
        ),
        indexing_threshold=get_int_value(values, "RAG_QDRANT_INDEXING_THRESHOLD", 2000),
        prevent_unoptimized=get_bool_value(
            values,
            "RAG_QDRANT_PREVENT_UNOPTIMIZED",
            False,
        ),
    )


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
        command_topic=get_value(
            values,
            "RETRIEVAL_INDEX_HELPER_COMMAND_TOPIC",
            TOPICS.helper_retrieval_index_commands,
        ),
    )


