"""Retrieval component configuration helpers."""

from __future__ import annotations

from dataclasses import dataclass

from configs.config import get_bool_value, get_value


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
