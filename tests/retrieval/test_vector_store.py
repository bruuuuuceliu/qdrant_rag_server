"""Qdrant vector store collection dimension checks (C3).

Covers the collection-creation path that ``memory_ingest`` actually exercises
(dense-only ``ensure_collection_exists``) plus the hybrid validator:
- stale-dimension existing collections fail loudly instead of surfacing the
  mismatch at upsert time;
- correct-dimension existing collections are validated and not re-created.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from retrieval_service.services.vector_store import (
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
