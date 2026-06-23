"""Retrieval indexing facade for chunk upserts."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from retrieval_service.indexing.sparse_text import (
    _attach_sparse_text,
    _build_sparse_text,
)
from retrieval_service.pipeline.helpers import _encode_batch
from retrieval_service.placement.execution import (
    PlacementStoreResolver,
    placement_write_targets,
)
from retrieval_service.retrieval.config import (
    ProjectRetrievalSettings,
    parse_retrieval_settings,
)
from retrieval_service.services.entities import (
    NerExtractor,
    NoopNerExtractor,
    entities_to_metadata,
)
from retrieval_service.services.sparse_encoder import SparseTextEncoder
from retrieval_service.services.vector_store import QdrantStore


@dataclass(frozen=True, slots=True)
class IndexChunksRequest:
    collection_name: str
    chunks: list[Any]
    payloads: list[Any]
    retrieval_config: dict[str, Any]
    job_id: str = ""
    placement_plan: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class IndexChunksResult:
    chunk_count: int
    dense_enabled: bool
    sparse_enabled: bool


class IndexingService:
    """Owns embedding, sparse-vector, entity enrichment, and Qdrant upsert."""

    def __init__(
        self,
        *,
        embedding_provider: Any,
        qdrant_store: QdrantStore,
        sparse_encoder: SparseTextEncoder | None = None,
        ner_extractor: NerExtractor | None = None,
        placement_store_resolver: PlacementStoreResolver | None = None,
        default_top_k: int = 5,
        default_candidate_count: int = 20,
    ) -> None:
        self._embedding_provider = embedding_provider
        self._qdrant_store = qdrant_store
        self._placement_store_resolver = placement_store_resolver or PlacementStoreResolver(
            default_store=qdrant_store,
        )
        self._sparse_encoder = sparse_encoder
        self._ner_extractor = ner_extractor or NoopNerExtractor()
        self._default_top_k = default_top_k
        self._default_candidate_count = default_candidate_count

    async def index_chunks(self, request: IndexChunksRequest) -> IndexChunksResult:
        if len(request.chunks) != len(request.payloads):
            raise ValueError(
                "indexing request must have matching chunk and payload counts"
            )

        settings = parse_retrieval_settings(
            request.retrieval_config,
            default_top_k=self._default_top_k,
            default_candidate_count=self._default_candidate_count,
        )
        if not request.chunks:
            return IndexChunksResult(
                chunk_count=0,
                dense_enabled=settings.dense_enabled,
                sparse_enabled=settings.bm25_enabled,
            )

        targets = placement_write_targets(
            request.placement_plan,
            fallback_collection_name=request.collection_name,
        )

        texts = [chunk.text for chunk in request.chunks]
        payloads = await self._enrich_payloads_with_entities(
            request.payloads,
            texts=texts,
            settings=settings,
        )
        vectors = None
        if settings.dense_enabled:
            vectors = await _encode_batch(self._embedding_provider, texts)

        if settings.bm25_enabled:
            if self._sparse_encoder is None:
                raise ValueError(
                    "BM25 retrieval is enabled but no sparse encoder is configured"
                )
            sparse_texts = [
                _build_sparse_text(
                    chunk.text,
                    getattr(chunk, "metadata", {}) or {},
                    lemmatize=settings.bm25.lemmatize,
                )
                for chunk in request.chunks
            ]
            sparse_vectors = await self._sparse_encoder.encode_batch(sparse_texts)
            payloads = _attach_sparse_text(
                payloads,
                sparse_texts,
                field_name=settings.bm25.text_field,
            )
            ids = [
                str(getattr(payload, "chunk_id", index))
                for index, payload in enumerate(payloads)
            ]
            for target in targets:
                qdrant_store = await self._placement_store_resolver.resolve(target)
                await qdrant_store.upsert_hybrid_points(
                    collection_name=target.collection_name,
                    dense_vectors=vectors,
                    sparse_vectors=sparse_vectors,
                    payloads=payloads,
                    ids=ids,
                    dense_vector_name=settings.bm25.dense_vector_name,
                    sparse_vector_name=settings.bm25.sparse_vector_name,
                )
        elif vectors is not None:
            for target in targets:
                qdrant_store = await self._placement_store_resolver.resolve(target)
                await qdrant_store.upsert(
                    collection_name=target.collection_name,
                    vectors=vectors,
                    payloads=payloads,
                )

        return IndexChunksResult(
            chunk_count=len(request.chunks),
            dense_enabled=settings.dense_enabled,
            sparse_enabled=settings.bm25_enabled,
        )

    async def shutdown(self) -> None:
        await self._placement_store_resolver.close()

    async def _enrich_payloads_with_entities(
        self,
        payloads: list[Any],
        *,
        texts: list[str],
        settings: ProjectRetrievalSettings,
    ) -> list[Any]:
        if not settings.ner.enabled:
            return payloads
        entities_by_chunk = await self._ner_extractor.extract_batch(texts)
        enriched: list[Any] = []
        for payload, entities in zip(payloads, entities_by_chunk):
            if not entities:
                enriched.append(payload)
                continue
            metadata = dict(getattr(payload, "metadata", {}) or {})
            metadata.update(entities_to_metadata(entities))
            enriched.append(replace(payload, metadata=metadata))
        return enriched
