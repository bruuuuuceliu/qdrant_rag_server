"""Async Qdrant vector store for the RAG engine.

Manages collection lifecycle, upsert, and filtered search.  All Qdrant
calls respect ``project_id``, ``user_id``, and ``kb_id`` isolation.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from rag_server.core.models import BaseChunkPayload

try:
    from qdrant_client import AsyncQdrantClient, models
    from qdrant_client.http.exceptions import UnexpectedResponse
except ModuleNotFoundError:
    AsyncQdrantClient = None  # type: ignore[assignment]
    models = None  # type: ignore[assignment]

    class UnexpectedResponse(Exception):
        pass


logger = logging.getLogger(__name__)

VECTOR_SIZE = 768
QDRANT_POINT_NAMESPACE = uuid.UUID("17f0b93e-60ff-5bcb-b2ac-7c1edfb8a2ad")


class QdrantStore:
    """Async wrapper around Qdrant for retrieval and indexing."""

    def __init__(
        self,
        *,
        url: str | None = None,
        host: str = "localhost",
        port: int = 6333,
        default_vector_size: int = VECTOR_SIZE,
        **kwargs: Any,
    ) -> None:
        if AsyncQdrantClient is None:
            raise RuntimeError(
                "qdrant_client is required to use QdrantStore. "
                "Install project dependencies with python -m pip install -e '.[dev]'."
            )
        if url is not None:
            self._client = AsyncQdrantClient(url=url, **kwargs)
        else:
            self._client = AsyncQdrantClient(host=host, port=port, **kwargs)
        self._default_vector_size = default_vector_size
        self._collection_locks: dict[str, asyncio.Lock] = {}

    async def ensure_collection_exists(
        self,
        collection_name: str,
        *,
        vector_size: int | None = None,
    ) -> None:
        vector_size = vector_size or self._default_vector_size
        lock = self._collection_locks.setdefault(
            collection_name, asyncio.Lock()
        )
        async with lock:
            exists = await self._collection_exists(collection_name)
            if not exists:
                await self._client.create_collection(
                    collection_name=collection_name,
                    vectors_config=models.VectorParams(
                        size=vector_size,
                        distance=models.Distance.COSINE,
                    ),
                )
                logger.info("created collection %s", collection_name)

    async def _collection_exists(self, collection_name: str) -> bool:
        try:
            await self._client.get_collection(collection_name)
            return True
        except (UnexpectedResponse, ValueError):
            return False

    async def upsert(
        self,
        collection_name: str,
        vectors: list[list[float]],
        payloads: list[BaseChunkPayload],
        *,
        vector_size: int | None = None,
    ) -> None:
        vector_size = vector_size or self._default_vector_size
        _validate_upsert_input(vectors, payloads, vector_size)
        if not payloads:
            return

        await self.ensure_collection_exists(collection_name, vector_size=vector_size)
        points = [
            models.PointStruct(
                id=make_qdrant_point_id(payload),
                vector=vector,
                payload=payload.to_qdrant_payload(),
            )
            for vector, payload in zip(vectors, payloads)
        ]
        await self._client.upsert(collection_name=collection_name, points=points)

    async def search(
        self,
        *,
        collection_name: str,
        query_vector: list[float],
        query_filter: models.Filter,
        limit: int = 5,
        with_payload: bool = True,
    ) -> list[models.ScoredPoint]:
        return await self._client.search(
            collection_name=collection_name,
            query_vector=query_vector,
            query_filter=query_filter,
            limit=limit,
            with_payload=with_payload,
        )

    async def delete_document(
        self,
        *,
        collection_name: str,
        project_id: str,
        user_id: str,
        kb_id: str,
        doc_id: str,
    ) -> None:
        await self._client.delete(
            collection_name=collection_name,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        _match_value("project_id", project_id),
                        _match_value("user_id", user_id),
                        _match_value("kb_id", kb_id),
                        _match_value("doc_id", doc_id),
                    ]
                )
            ),
        )

    async def delete_project(self, collection_name: str) -> None:
        await self._client.delete_collection(collection_name)
        logger.info("deleted collection %s", collection_name)

    async def collection_info(self, collection_name: str) -> dict[str, Any] | None:
        try:
            info = await self._client.get_collection(collection_name)
            return info.dict() if hasattr(info, "dict") else vars(info)
        except (UnexpectedResponse, ValueError):
            return None

    async def close(self) -> None:
        await self._client.close()


def make_qdrant_point_id(payload: BaseChunkPayload) -> str:
    """Return a deterministic UUID built from tenant-safe point identity."""

    raw = "|".join(
        [
            payload.project_id,
            payload.user_id,
            payload.kb_id,
            payload.doc_id,
            payload.data_type,
            str(payload.chunk_index),
            payload.chunker_version,
        ]
    )
    return str(uuid.uuid5(QDRANT_POINT_NAMESPACE, raw))


def _validate_upsert_input(
    vectors: list[list[float]],
    payloads: list[BaseChunkPayload],
    vector_size: int,
) -> None:
    if len(vectors) != len(payloads):
        raise ValueError(
            "vector count must match payload count: "
            f"vectors={len(vectors)} payloads={len(payloads)}"
        )
    for index, vector in enumerate(vectors):
        if len(vector) != vector_size:
            raise ValueError(
                f"vector at index {index} has dimension {len(vector)}; "
                f"expected {vector_size}"
            )


def _match_value(key: str, value: str) -> models.FieldCondition:
    return models.FieldCondition(
        key=key,
        match=models.MatchValue(value=value),
    )


@dataclass(frozen=True, slots=True)
class _FallbackMatchValue:
    value: str


@dataclass(frozen=True, slots=True)
class _FallbackMatchAny:
    any: list[str]


@dataclass(frozen=True, slots=True)
class _FallbackFieldCondition:
    key: str
    match: Any


@dataclass(frozen=True, slots=True)
class _FallbackFilter:
    must: list[Any]


@dataclass(frozen=True, slots=True)
class _FallbackFilterSelector:
    filter: Any


@dataclass(frozen=True, slots=True)
class _FallbackPointStruct:
    id: str
    vector: list[float]
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class _FallbackVectorParams:
    size: int
    distance: str


class _FallbackDistance:
    COSINE = "Cosine"


class _FallbackQdrantModels:
    MatchValue = _FallbackMatchValue
    MatchAny = _FallbackMatchAny
    FieldCondition = _FallbackFieldCondition
    Filter = _FallbackFilter
    FilterSelector = _FallbackFilterSelector
    PointStruct = _FallbackPointStruct
    VectorParams = _FallbackVectorParams
    Distance = _FallbackDistance


if models is None:
    models = _FallbackQdrantModels()  # type: ignore[assignment]
