"""Qdrant vector store collection lifecycle tests (C3 dimension + C4 HNSW).

Covers the collection-creation path that ``memory_ingest`` actually exercises
(dense-only ``ensure_collection_exists``) plus the hybrid validator:
- stale-dimension existing collections fail loudly instead of surfacing the
  mismatch at upsert time;
- correct-dimension existing collections are validated and not re-created;
- fresh collections are created with the single default index profile
  (``full_scan_threshold`` in ``hnsw_config``; ``indexing_threshold`` /
  ``prevent_unoptimized`` in ``optimizers_config``).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from retrieval_service.services.vector_store import (
    CollectionIndexConfig,
    QdrantStore,
    _named_vector_size,
    _unnamed_vector_size,
)


class _Info:
    """Minimal stand-in for a Qdrant CollectionInfo with a ``.dict()``."""

    def __init__(self, data: dict) -> None:
        self._data = data

    def dict(self) -> dict:
        return self._data


def _dense_info(size: int) -> dict:
    return {"config": {"params": {"vectors": {"size": size, "distance": "Cosine"}}}}


def _hybrid_info(
    size: int,
    *,
    dense_name: str = "dense",
    sparse_name: str = "bm25",
) -> dict:
    return {
        "config": {
            "params": {
                "vectors": {dense_name: {"size": size, "distance": "Cosine"}},
                "sparse_vectors": {sparse_name: {"modifier": "idf"}},
            }
        }
    }


def _make_store(client, **kwargs):
    with patch(
        "retrieval_service.services.vector_store.AsyncQdrantClient",
        return_value=client,
    ):
        return QdrantStore(default_vector_size=768, **kwargs)


# --- C3: stale-dimension checks on the dense-only collection path -----------


@pytest.mark.asyncio
async def test_ensure_collection_exists_rejects_stale_dimension() -> None:
    client = AsyncMock()
    client.get_collection = AsyncMock(return_value=_Info(_dense_info(384)))
    store = _make_store(client)

    with pytest.raises(ValueError, match=r"has vector dimension 384; expected 768"):
        await store.ensure_collection_exists("agent_memory")

    client.create_collection.assert_not_awaited()


@pytest.mark.asyncio
async def test_ensure_collection_exists_accepts_correct_dimension() -> None:
    client = AsyncMock()
    client.get_collection = AsyncMock(return_value=_Info(_dense_info(768)))
    store = _make_store(client)

    await store.ensure_collection_exists("agent_memory")

    client.create_collection.assert_not_awaited()
    client.get_collection.assert_awaited_with("agent_memory")


@pytest.mark.asyncio
async def test_ensure_hybrid_collection_exists_rejects_stale_dense_dimension() -> None:
    client = AsyncMock()
    client.get_collection = AsyncMock(return_value=_Info(_hybrid_info(384)))
    store = _make_store(client)

    with pytest.raises(ValueError, match=r"has vector dimension 384; expected 768"):
        await store.ensure_hybrid_collection_exists(
            "agent_memory_hybrid",
            dense_vector_size=768,
        )

    client.create_collection.assert_not_awaited()


@pytest.mark.asyncio
async def test_ensure_hybrid_collection_exists_accepts_correct_dimension() -> None:
    client = AsyncMock()
    client.get_collection = AsyncMock(return_value=_Info(_hybrid_info(768)))
    store = _make_store(client)

    await store.ensure_hybrid_collection_exists(
        "agent_memory_hybrid",
        dense_vector_size=768,
    )

    client.create_collection.assert_not_awaited()


# --- C4: HNSW / optimizer config applied only at creation -------------------


@pytest.mark.asyncio
async def test_ensure_collection_exists_creates_fresh_collection_with_index_config() -> None:
    client = AsyncMock()
    client.get_collection = AsyncMock(side_effect=ValueError("not found"))
    store = _make_store(client)

    await store.ensure_collection_exists("agent_memory")

    client.create_collection.assert_awaited_once()
    kwargs = client.create_collection.call_args.kwargs
    hnsw = kwargs["hnsw_config"]
    optimizers = kwargs["optimizers_config"]
    assert hnsw.m == 16
    assert hnsw.ef_construct == 100
    assert hnsw.full_scan_threshold == 10000
    assert optimizers.indexing_threshold == 2000
    assert optimizers.prevent_unoptimized is False


@pytest.mark.asyncio
async def test_ensure_hybrid_collection_exists_creates_fresh_collection_with_index_config() -> None:
    client = AsyncMock()
    client.get_collection = AsyncMock(side_effect=ValueError("not found"))
    store = _make_store(client)

    await store.ensure_hybrid_collection_exists(
        "agent_memory_hybrid",
        dense_vector_size=768,
    )

    client.create_collection.assert_awaited_once()
    kwargs = client.create_collection.call_args.kwargs
    assert kwargs["hnsw_config"].m == 16
    assert kwargs["hnsw_config"].ef_construct == 100
    assert kwargs["hnsw_config"].full_scan_threshold == 10000
    assert kwargs["optimizers_config"].indexing_threshold == 2000
    assert kwargs["optimizers_config"].prevent_unoptimized is False


@pytest.mark.asyncio
async def test_custom_index_config_applied_at_creation() -> None:
    client = AsyncMock()
    client.get_collection = AsyncMock(side_effect=ValueError("not found"))
    store = _make_store(
        client,
        collection_index_config=CollectionIndexConfig(
            hnsw_m=32,
            hnsw_ef_construct=200,
            full_scan_threshold=5000,
            indexing_threshold=1000,
            prevent_unoptimized=True,
        ),
    )

    await store.ensure_collection_exists("agent_memory")

    kwargs = client.create_collection.call_args.kwargs
    assert kwargs["hnsw_config"].m == 32
    assert kwargs["hnsw_config"].ef_construct == 200
    assert kwargs["hnsw_config"].full_scan_threshold == 5000
    assert kwargs["optimizers_config"].indexing_threshold == 1000
    assert kwargs["optimizers_config"].prevent_unoptimized is True


@pytest.mark.asyncio
async def test_pre_existing_collection_not_recreated_config_untouched() -> None:
    client = AsyncMock()
    client.get_collection = AsyncMock(return_value=_Info(_dense_info(768)))
    store = _make_store(client)

    await store.ensure_collection_exists("agent_memory")

    client.create_collection.assert_not_awaited()
    client.upsert.assert_not_awaited()


# --- C3: vector-size helper edge cases --------------------------------------


def test_unnamed_vector_size_direct_size_key() -> None:
    info = {"config": {"params": {"vectors": {"size": 768, "distance": "Cosine"}}}}
    assert _unnamed_vector_size(info) == 768


def test_unnamed_vector_size_empty_string_key() -> None:
    info = {
        "config": {
            "params": {"vectors": {"": {"size": 384, "distance": "Cosine"}}}
        }
    }
    assert _unnamed_vector_size(info) == 384


def test_unnamed_vector_size_named_only_returns_none() -> None:
    info = {"config": {"params": {"vectors": {"dense": {"size": 768}}}}}
    assert _unnamed_vector_size(info) is None


def test_unnamed_vector_size_missing_structure_returns_none() -> None:
    assert _unnamed_vector_size({}) is None
    assert _unnamed_vector_size({"config": {}}) is None
    assert _unnamed_vector_size({"config": {"params": {}}}) is None


def test_named_vector_size_finds_exact_name() -> None:
    info = {
        "config": {
            "params": {
                "vectors": {
                    "dense": {"size": 768, "distance": "Cosine"},
                    "other": {"size": 5},
                }
            }
        }
    }
    assert _named_vector_size(info, "dense") == 768
    assert _named_vector_size(info, "other") == 5
    assert _named_vector_size(info, "missing") is None
