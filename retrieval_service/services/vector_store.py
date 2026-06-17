"""Async Qdrant vector store.

Manages collection lifecycle, upsert, and filtered search. Service-specific
filter translators are responsible for isolation semantics.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from retrieval_service.services.sparse_encoder import SparseVector

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


class VectorPayload(Protocol):
    """Minimal payload contract needed by QdrantStore."""

    def to_qdrant_payload(self) -> dict[str, Any]:
        ...

    def point_identity(self) -> tuple[str, ...]:
        ...


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

    async def ensure_hybrid_collection_exists(
        self,
        collection_name: str,
        *,
        dense_vector_name: str = "dense",
        dense_vector_size: int | None = None,
        sparse_vector_name: str = "bm25",
    ) -> None:
        dense_vector_size = dense_vector_size or self._default_vector_size
        lock = self._collection_locks.setdefault(
            collection_name, asyncio.Lock()
        )
        async with lock:
            info = await self.collection_info(collection_name)
            if info is not None:
                _validate_hybrid_collection_schema(
                    collection_name=collection_name,
                    info=info,
                    dense_vector_name=dense_vector_name,
                    sparse_vector_name=sparse_vector_name,
                )
                return
            await self._client.create_collection(
                collection_name=collection_name,
                vectors_config={
                    dense_vector_name: models.VectorParams(
                        size=dense_vector_size,
                        distance=models.Distance.COSINE,
                    )
                },
                sparse_vectors_config={
                    sparse_vector_name: _sparse_vector_params(),
                },
            )
            logger.info(
                "created hybrid collection %s dense=%s sparse=%s",
                collection_name,
                dense_vector_name,
                sparse_vector_name,
            )

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
        payloads: list[VectorPayload],
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

    async def upsert_hybrid_points(
        self,
        collection_name: str,
        *,
        dense_vectors: list[list[float]] | None,
        sparse_vectors: list[Any],
        payloads: list[VectorPayload],
        ids: list[str] | None = None,
        dense_vector_name: str = "dense",
        sparse_vector_name: str = "bm25",
        vector_size: int | None = None,
    ) -> None:
        vector_size = vector_size or self._default_vector_size
        _validate_hybrid_upsert_input(
            dense_vectors=dense_vectors,
            sparse_vectors=sparse_vectors,
            payloads=payloads,
            ids=ids,
            vector_size=vector_size,
        )
        if not payloads:
            return

        await self.ensure_hybrid_collection_exists(
            collection_name,
            dense_vector_name=dense_vector_name,
            dense_vector_size=vector_size,
            sparse_vector_name=sparse_vector_name,
        )
        points = []
        for index, payload in enumerate(payloads):
            vector: dict[str, Any] = {
                sparse_vector_name: _to_qdrant_sparse_vector(sparse_vectors[index])
            }
            if dense_vectors is not None:
                vector[dense_vector_name] = dense_vectors[index]
            points.append(
                models.PointStruct(
                    id=make_qdrant_point_id(payload),
                    vector=vector,
                    payload=payload.to_qdrant_payload(),
                )
            )
        await self._client.upsert(collection_name=collection_name, points=points)

    async def search(
        self,
        *,
        collection_name: str,
        query_vector: list[float],
        query_filter: models.Filter,
        limit: int = 5,
        with_payload: bool = True,
        vector_name: str | None = None,
    ) -> list[models.ScoredPoint]:
        if hasattr(self._client, "search"):
            query_vector_arg: Any = query_vector
            if vector_name:
                query_vector_arg = (vector_name, query_vector)
            return await self._client.search(
                collection_name=collection_name,
                query_vector=query_vector_arg,
                query_filter=query_filter,
                limit=limit,
                with_payload=with_payload,
            )

        kwargs: dict[str, Any] = {}
        if vector_name:
            kwargs["using"] = vector_name
        response = await self._client.query_points(
            collection_name=collection_name,
            query=query_vector,
            query_filter=query_filter,
            limit=limit,
            with_payload=with_payload,
            **kwargs,
        )
        return response.points if hasattr(response, "points") else response

    async def search_sparse(
        self,
        *,
        collection_name: str,
        sparse_vector_name: str,
        query_sparse_vector: Any,
        query_filter: models.Filter,
        limit: int = 5,
        with_payload: bool = True,
    ) -> list[models.ScoredPoint]:
        await self.ensure_sparse_vector_exists(
            collection_name=collection_name,
            sparse_vector_name=sparse_vector_name,
        )
        response = await self._client.query_points(
            collection_name=collection_name,
            query=_to_qdrant_sparse_vector(query_sparse_vector),
            using=sparse_vector_name,
            query_filter=query_filter,
            limit=limit,
            with_payload=with_payload,
        )
        return response.points if hasattr(response, "points") else response

    async def ensure_sparse_vector_exists(
        self,
        *,
        collection_name: str,
        sparse_vector_name: str,
    ) -> None:
        info = await self.collection_info(collection_name)
        if info is None:
            raise ValueError(
                f"collection {collection_name!r} does not exist; reingest before "
                "running sparse retrieval"
            )
        if not _has_named_sparse_vector(info, sparse_vector_name):
            raise ValueError(
                f"collection {collection_name!r} exists but is not compatible with "
                f"sparse retrieval; missing sparse vector {sparse_vector_name!r}. "
                "Use a collection created for hybrid retrieval or reingest into "
                "a new collection version."
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


def make_qdrant_point_id(payload: VectorPayload) -> str:
    """Return a deterministic UUID built from the payload identity."""

    if hasattr(payload, "point_identity"):
        raw = "|".join(str(part) for part in payload.point_identity())
    else:
        rendered = payload.to_qdrant_payload()
        raw = "|".join(
            str(rendered.get(key, ""))
            for key in ("payload_id", "chunk_id", "data_type", "chunk_index")
        )
    return str(uuid.uuid5(QDRANT_POINT_NAMESPACE, raw))


def _validate_upsert_input(
    vectors: list[list[float]],
    payloads: list[VectorPayload],
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


def _validate_hybrid_upsert_input(
    *,
    dense_vectors: list[list[float]] | None,
    sparse_vectors: list[Any],
    payloads: list[VectorPayload],
    ids: list[str] | None,
    vector_size: int,
) -> None:
    if len(sparse_vectors) != len(payloads):
        raise ValueError(
            "sparse vector count must match payload count: "
            f"sparse_vectors={len(sparse_vectors)} payloads={len(payloads)}"
        )
    if dense_vectors is not None:
        _validate_upsert_input(dense_vectors, payloads, vector_size)
    if ids is not None and len(ids) != len(payloads):
        raise ValueError(
            "id count must match payload count: "
            f"ids={len(ids)} payloads={len(payloads)}"
        )


def _to_qdrant_sparse_vector(vector: Any) -> Any:
    if hasattr(vector, "indices") and hasattr(vector, "values"):
        indices = [int(index) for index in vector.indices]
        values = [float(value) for value in vector.values]
    elif isinstance(vector, dict):
        indices = [int(index) for index in vector.get("indices", [])]
        values = [float(value) for value in vector.get("values", [])]
    else:
        raise ValueError("sparse vector must provide indices and values")
    if hasattr(models, "SparseVector"):
        return models.SparseVector(indices=indices, values=values)
    return SparseVector(indices=indices, values=values)


def _sparse_vector_params() -> Any:
    if hasattr(models, "SparseVectorParams"):
        if hasattr(models, "Modifier"):
            return models.SparseVectorParams(modifier=models.Modifier.IDF)
        return models.SparseVectorParams()
    return _FallbackSparseVectorParams(modifier="idf")


def _validate_hybrid_collection_schema(
    *,
    collection_name: str,
    info: dict[str, Any],
    dense_vector_name: str,
    sparse_vector_name: str,
) -> None:
    missing: list[str] = []
    if not _has_named_vector(info, dense_vector_name):
        missing.append(f"named dense vector {dense_vector_name!r}")
    if not _has_named_sparse_vector(info, sparse_vector_name):
        missing.append(f"sparse vector {sparse_vector_name!r}")
    if missing:
        joined = " and ".join(missing)
        raise ValueError(
            f"collection {collection_name!r} exists but is not compatible with "
            f"hybrid retrieval; missing {joined}. Use a collection created for "
            "hybrid retrieval, reingest into a new collection version, or delete "
            "the incompatible showcase collection before rerunning."
        )


def _has_named_vector(info: dict[str, Any], vector_name: str) -> bool:
    vectors = _collection_params(info).get("vectors")
    return isinstance(vectors, dict) and vector_name in vectors


def _has_named_sparse_vector(info: dict[str, Any], vector_name: str) -> bool:
    sparse_vectors = _collection_params(info).get("sparse_vectors")
    return isinstance(sparse_vectors, dict) and vector_name in sparse_vectors


def _collection_params(info: dict[str, Any]) -> dict[str, Any]:
    config = info.get("config")
    if not isinstance(config, dict):
        return {}
    params = config.get("params")
    return params if isinstance(params, dict) else {}


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
    vector: Any
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class _FallbackVectorParams:
    size: int
    distance: str


@dataclass(frozen=True, slots=True)
class _FallbackSparseVectorParams:
    modifier: str | None = None


@dataclass(frozen=True, slots=True)
class _FallbackSparseVector:
    indices: list[int]
    values: list[float]


class _FallbackDistance:
    COSINE = "Cosine"


class _FallbackModifier:
    IDF = "idf"


class _FallbackQdrantModels:
    MatchValue = _FallbackMatchValue
    MatchAny = _FallbackMatchAny
    FieldCondition = _FallbackFieldCondition
    Filter = _FallbackFilter
    FilterSelector = _FallbackFilterSelector
    PointStruct = _FallbackPointStruct
    VectorParams = _FallbackVectorParams
    SparseVector = _FallbackSparseVector
    SparseVectorParams = _FallbackSparseVectorParams
    Distance = _FallbackDistance
    Modifier = _FallbackModifier


if models is None:
    models = _FallbackQdrantModels()  # type: ignore[assignment]
