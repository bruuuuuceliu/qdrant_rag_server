"""Qdrant sparse BM25 retrieval services."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from retrieval_service.services.retriever import (
    RetrievalHit,
    RetrievalQuery,
    RetrieverSource,
)
from retrieval_service.services.vector_store import QdrantStore


@dataclass(frozen=True, slots=True)
class BM25ChunkRecord:
    collection_name: str
    chunk_id: str
    text: str
    payload: dict[str, Any]
    sparse_vector: Any | None = None
    filter_fields: dict[str, str | tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BM25Query:
    collection_name: str
    query_text: str
    query_sparse_vector: Any | None = None
    retrieval_filter: Any = None
    filter_fields: dict[str, str | tuple[str, ...]] = field(default_factory=dict)
    limit: int = 5


class BM25Index(Protocol):
    async def initialize(self) -> None:
        ...

    async def upsert_chunks(self, records: list[BM25ChunkRecord]) -> None:
        ...

    async def search(self, query: BM25Query) -> list[RetrievalHit]:
        ...

    async def delete_document(
        self,
        *,
        collection_name: str,
        filter_fields: dict[str, str | tuple[str, ...]],
    ) -> None:
        ...

    async def close(self) -> None:
        ...


class QdrantSparseBM25Index:
    """BM25-style sparse retrieval using a named sparse vector in Qdrant."""

    def __init__(
        self,
        *,
        store: QdrantStore,
        sparse_vector_name: str = "bm25",
    ) -> None:
        self._store = store
        self._sparse_vector_name = sparse_vector_name

    async def initialize(self) -> None:
        return None

    async def upsert_chunks(self, records: list[BM25ChunkRecord]) -> None:
        if not records:
            return
        missing = [record.chunk_id for record in records if record.sparse_vector is None]
        if missing:
            raise ValueError(
                "sparse_vector is required for Qdrant BM25 upsert; "
                f"missing chunk_ids={missing}"
            )
        first = records[0]
        await self._store.upsert_hybrid_points(
            collection_name=first.collection_name,
            dense_vectors=None,
            sparse_vectors=[record.sparse_vector for record in records],
            payloads=[_StaticPayload(record.payload) for record in records],
            ids=[record.chunk_id for record in records],
            sparse_vector_name=self._sparse_vector_name,
        )

    async def search(self, query: BM25Query) -> list[RetrievalHit]:
        if query.query_sparse_vector is None:
            raise ValueError("query_sparse_vector is required for BM25 retrieval")
        points = await self._store.search_sparse(
            collection_name=query.collection_name,
            sparse_vector_name=self._sparse_vector_name,
            query_sparse_vector=query.query_sparse_vector,
            query_filter=query.retrieval_filter,
            limit=query.limit,
        )
        hits: list[RetrievalHit] = []
        for index, point in enumerate(points):
            payload = point.payload if isinstance(point.payload, dict) else {}
            hits.append(
                RetrievalHit(
                    payload=payload,
                    score=float(point.score),
                    source="bm25",
                    rank=index + 1,
                    metadata={"sparse_vector_name": self._sparse_vector_name},
                )
            )
        return hits

    async def delete_document(
        self,
        *,
        collection_name: str,
        filter_fields: dict[str, str | tuple[str, ...]],
    ) -> None:
        return None

    async def close(self) -> None:
        return None


class BM25Retriever:
    """Retriever adapter for a Qdrant sparse BM25 index."""

    source: RetrieverSource = "bm25"

    def __init__(self, index: BM25Index) -> None:
        self._index = index

    async def search(self, query: RetrievalQuery) -> list[RetrievalHit]:
        filter_fields = dict(query.metadata.get("filter_fields", {}))
        return await self._index.search(
            BM25Query(
                collection_name=query.collection_name,
                query_text=query.query_text,
                query_sparse_vector=query.query_sparse_vector,
                retrieval_filter=query.retrieval_filter,
                filter_fields=filter_fields,
                limit=query.limit,
            )
        )


@dataclass(frozen=True, slots=True)
class _StaticPayload:
    payload: dict[str, Any]

    def to_qdrant_payload(self) -> dict[str, Any]:
        return dict(self.payload)

    def point_identity(self) -> tuple[str, ...]:
        return (
            str(self.payload.get("project_id", "")),
            str(self.payload.get("user_id", "")),
            str(self.payload.get("kb_id", "")),
            str(self.payload.get("doc_id", "")),
            str(self.payload.get("data_type", "")),
            str(self.payload.get("chunk_index", "")),
            str(self.payload.get("chunker_version", "")),
        )
