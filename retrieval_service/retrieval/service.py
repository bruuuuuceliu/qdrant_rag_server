"""Retrieval-service facade for search, delete, and raw-document operations."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from retrieval_service.indexing.sparse_text import _build_sparse_text
from retrieval_service.pipeline.helpers import _elapsed_ms, _encode_query
from retrieval_service.query.qdrant_filters import _build_qdrant_filter
from retrieval_service.ranking.entity_boost import (
    apply_entity_boosts,
    extract_query_entity_keys,
)
from retrieval_service.retrieval.config import (
    ProjectRetrievalSettings,
    parse_retrieval_settings,
)
from retrieval_service.retrieval.factory import ProjectRetrieverFactory
from retrieval_service.services.entities import (
    NerExtractor,
    NoopNerExtractor,
)
from retrieval_service.services.retriever import RetrievalHit, RetrievalQuery, Retriever
from retrieval_service.services.sparse_encoder import SparseTextEncoder
from retrieval_service.services.vector_store import QdrantStore


@dataclass(frozen=True, slots=True)
class RetrievalSearchRequest:
    project_id: str
    user_id: str
    query_text: str
    collection_name: str
    retrieval_config: dict[str, Any] = field(default_factory=dict)
    retrieval_filter: Any = None
    cache_key: str = ""


@dataclass(frozen=True, slots=True)
class RetrievalSearchResult:
    chunks: list[dict[str, Any]]
    elapsed_ms: int
    cache_hit: bool = False


@dataclass(frozen=True, slots=True)
class DeleteDocumentRequest:
    project_id: str
    user_id: str
    kb_id: str
    doc_id: str
    collection_name: str


@dataclass(frozen=True, slots=True)
class RawDocumentRequest:
    project_id: str
    user_id: str
    doc_id: str


class RetrievalService:
    """Owns retrieval-facing Qdrant, ranking, cache, and raw-storage calls."""

    def __init__(
        self,
        *,
        embedding_provider: Any,
        qdrant_store: QdrantStore,
        retriever_factory: ProjectRetrieverFactory,
        sparse_encoder: SparseTextEncoder | None = None,
        ner_extractor: NerExtractor | None = None,
        rerank_fn: Any = None,
        tier1_cache: Any = None,
        tier2_cache: Any = None,
        object_storage: Any = None,
        bm25_index: Any = None,
        metrics: Any = None,
        default_top_k: int = 5,
        default_candidate_count: int = 20,
    ) -> None:
        self._embedding_provider = embedding_provider
        self._qdrant_store = qdrant_store
        self._retriever_factory = retriever_factory
        self._sparse_encoder = sparse_encoder
        self._ner_extractor = ner_extractor or NoopNerExtractor()
        self._rerank_fn = rerank_fn
        self._tier1_cache = tier1_cache
        self._tier2_cache = tier2_cache
        self._object_storage = object_storage
        self._bm25_index = bm25_index
        self._metrics = metrics
        self._default_top_k = default_top_k
        self._default_candidate_count = default_candidate_count

    async def search(self, request: RetrievalSearchRequest) -> RetrievalSearchResult:
        start_ns = time.monotonic_ns()

        if self._metrics is not None:
            self._metrics.record_search_request()

        settings = parse_retrieval_settings(
            request.retrieval_config,
            default_top_k=self._default_top_k,
            default_candidate_count=self._default_candidate_count,
        )

        if self._tier1_cache is not None and request.cache_key:
            cached = await self._tier1_cache.get(request.project_id, request.cache_key)
            if cached is not None:
                cached = dict(cached)
                cached["cache_hit"] = True
                if self._metrics is not None:
                    self._metrics.record_search_cache_hit()
                    self._metrics.record_search_latency(_elapsed_float_ms(start_ns))
                cached["elapsed_ms"] = max(1, _elapsed_ms(start_ns))
                return RetrievalSearchResult(**cached)

        query = await self._build_query(request, settings=settings)
        search_results = await self._search_candidates(query=query, settings=settings)
        search_results = await self._apply_query_entity_boosts(
            request.query_text,
            search_results,
            settings=settings,
        )
        final = await self._finalize_hits(
            request.query_text,
            search_results,
            top_k=settings.top_k,
        )
        chunks = _chunks_from_hits(final)
        elapsed_ms = max(1, _elapsed_ms(start_ns))
        result = RetrievalSearchResult(
            chunks=chunks,
            elapsed_ms=elapsed_ms,
            cache_hit=False,
        )

        if self._tier1_cache is not None and request.cache_key:
            await self._tier1_cache.set(
                request.project_id,
                request.cache_key,
                {"chunks": chunks, "elapsed_ms": result.elapsed_ms},
            )

        if self._metrics is not None:
            self._metrics.record_search_latency(_elapsed_float_ms(start_ns))

        return result

    async def delete_document(self, request: DeleteDocumentRequest) -> None:
        await self._qdrant_store.delete_document(
            collection_name=request.collection_name,
            project_id=request.project_id,
            user_id=request.user_id,
            kb_id=request.kb_id,
            doc_id=request.doc_id,
        )
        try:
            if self._bm25_index is not None:
                await self._bm25_index.delete_document(
                    collection_name=request.collection_name,
                    filter_fields={
                        "project_id": request.project_id,
                        "user_id": request.user_id,
                        "kb_id": request.kb_id,
                        "doc_id": request.doc_id,
                    },
                )
            if self._object_storage is not None:
                from retrieval_service.storage.base import make_storage_key

                storage_key = make_storage_key(
                    request.project_id,
                    request.user_id,
                    request.doc_id,
                )
                await self._object_storage.delete(storage_key)
        finally:
            await self._invalidate_document_caches(
                project_id=request.project_id,
                user_id=request.user_id,
            )

    async def _invalidate_document_caches(self, *, project_id: str, user_id: str) -> None:
        if self._tier1_cache is not None:
            await self._tier1_cache.invalidate_project(project_id)
        if self._tier2_cache is not None:
            await self._tier2_cache.invalidate_user(project_id, user_id)

    async def get_raw_document(self, request: RawDocumentRequest) -> bytes | None:
        if self._object_storage is None:
            return None

        from retrieval_service.storage.base import ObjectStorageError, make_storage_key

        storage_key = make_storage_key(
            request.project_id,
            request.user_id,
            request.doc_id,
        )
        try:
            return await self._object_storage.get(storage_key)
        except ObjectStorageError:
            return None

    async def _build_query(
        self,
        request: RetrievalSearchRequest,
        *,
        settings: ProjectRetrievalSettings,
    ) -> RetrievalQuery:
        _validate_retrieval_filter(request.retrieval_filter)
        qdrant_filter = _build_qdrant_filter(request.retrieval_filter)
        query_vector = None
        if settings.dense_enabled:
            query_vector = await _encode_query(
                self._embedding_provider,
                request.query_text,
            )
        query_sparse_vector = None
        if settings.bm25_enabled:
            if self._sparse_encoder is None:
                raise ValueError(
                    "BM25 retrieval is enabled but no sparse encoder is configured"
                )
            query_sparse_vector = await self._sparse_encoder.encode(
                _build_sparse_text(
                    request.query_text,
                    {},
                    lemmatize=settings.bm25.lemmatize,
                )
            )

        return RetrievalQuery(
            collection_name=request.collection_name,
            query_text=request.query_text,
            query_vector=query_vector,
            query_sparse_vector=query_sparse_vector,
            retrieval_filter=qdrant_filter,
            limit=settings.candidate_count,
            metadata={
                "filter_fields": _build_filter_fields(request.retrieval_filter),
                "dense_vector_name": (
                    settings.bm25.dense_vector_name
                    if settings.bm25.use_named_dense_vector
                    else None
                ),
            },
        )

    async def _search_candidates(
        self,
        *,
        query: RetrievalQuery,
        settings: ProjectRetrievalSettings,
    ) -> list[RetrievalHit]:
        retriever: Retriever = self._retriever_factory.build(settings=settings)
        return await retriever.search(query)

    async def _apply_query_entity_boosts(
        self,
        query_text: str,
        hits: list[RetrievalHit],
        *,
        settings: ProjectRetrievalSettings,
    ) -> list[RetrievalHit]:
        if not settings.ner.enabled or not settings.ner.boost_entities:
            return hits
        query_entities = await self._ner_extractor.extract(query_text)
        return apply_entity_boosts(
            hits,
            query_entity_keys=extract_query_entity_keys(query_entities=query_entities),
            boost=settings.ner.entity_boost,
        )

    async def _finalize_hits(
        self,
        query_text: str,
        hits: list[RetrievalHit],
        *,
        top_k: int,
    ) -> list[tuple[dict[str, Any], float]]:
        if self._rerank_fn is not None and hits:
            pairs = [(hit.payload, hit.score) for hit in hits if hit.payload is not None]
            return (await self._rerank_fn(query_text, pairs))[:top_k]
        return [(hit.payload, hit.score) for hit in hits[:top_k] if hit.payload]


def _chunks_from_hits(final: list[tuple[dict[str, Any], float]]) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for payload_data, score in final:
        chunk = dict(payload_data) if isinstance(payload_data, dict) else {}
        chunk["score"] = score
        chunks.append(chunk)
    return chunks


def _build_filter_fields(retrieval_filter: Any) -> dict[str, str | tuple[str, ...]]:
    fields: dict[str, str | tuple[str, ...]] = {
        "project_id": retrieval_filter.project_id,
        "user_id": tuple(retrieval_filter.allowed_user_ids),
    }
    if getattr(retrieval_filter, "kb_ids", ()):
        fields["kb_id"] = tuple(retrieval_filter.kb_ids)
    if getattr(retrieval_filter, "doc_ids", ()):
        fields["doc_id"] = tuple(retrieval_filter.doc_ids)
    return fields


def _validate_retrieval_filter(retrieval_filter: Any) -> None:
    if retrieval_filter is None:
        raise ValueError("retrieval_filter is required")
    missing = [
        name
        for name in ("project_id", "allowed_user_ids")
        if not hasattr(retrieval_filter, name)
    ]
    if missing:
        raise ValueError(
            "retrieval_filter is missing required fields: " + ", ".join(missing)
        )


def _elapsed_float_ms(start_ns: int) -> float:
    return (time.monotonic_ns() - start_ns) / 1e6
