"""Opt-in live Qdrant bge-768 collection round-trip (C3 migration + C4 HNSW).

Proves the runtime path that ``memory_ingest`` uses end-to-end against a real
Qdrant and the real local bge-768 model:

1. ``agent_memory`` is DELETED (delete-and-reindex migration), so it is
   re-created lazily at 768-dim on the next ingest.
2. One memory chunk is indexed through ``IndexingService.index_chunks`` (the
   exact code path the ``memory_ingest`` helper command drives).
3. A memory-scoped dense search returns a hit (the Qdrant call ``memory.lookup``
   performs through the memory searcher).
4. ``collection_info`` shows ``size=768`` and the C4 HNSW/optimizer profile.

Marked ``live_infra`` and skipped unless ``RAG_LIVE_INFRA=1`` and Qdrant is
reachable, so the default suite (including ``tests/retrieval``) never loads the
real bge checkpoint.
"""

from __future__ import annotations

import os
import urllib.request

import pytest

from retrieval_service.embedding.local import LocalSentenceTransformerEmbedding
from retrieval_service.indexing import IndexChunksRequest, IndexingService
from retrieval_service.memory.schemas.documents import MemoryChunk, MemoryChunkPayload
from retrieval_service.services.vector_store import (
    CollectionIndexConfig,
    QdrantStore,
    models,
)

pytestmark = pytest.mark.live_infra

QDRANT_HTTP = os.environ.get("RAG_QDRANT_URL", "http://localhost:6333")


def _require_live_infra() -> None:
    if os.environ.get("RAG_LIVE_INFRA") != "1":
        pytest.skip("set RAG_LIVE_INFRA=1 to run live Qdrant bge-768 tests")
    try:
        with urllib.request.urlopen(f"{QDRANT_HTTP}/collections", timeout=3) as response:
            assert response.status == 200
    except Exception as exc:  # pragma: no cover - depends on external infra
        pytest.skip(f"Qdrant not reachable at {QDRANT_HTTP}: {exc}")


@pytest.mark.asyncio
async def test_bge768_round_trip_deletes_recreates_memory_collection() -> None:
    _require_live_infra()
    store = QdrantStore(
        url=QDRANT_HTTP,
        default_vector_size=768,
        collection_index_config=CollectionIndexConfig(),
    )
    embedding = LocalSentenceTransformerEmbedding(
        model_name="BAAI/bge-base-en-v1.5",
        dimension=768,
    )
    await embedding.initialize()
    try:
        # Delete-and-reindex migration (C3): the stale collection is dropped so
        # the next ingest recreates it lazily at 768-dim.
        await store.delete_project("agent_memory")

        indexing = IndexingService(
            embedding_provider=embedding,
            qdrant_store=store,
        )
        chunk = MemoryChunk(
            chunk_id="mem_live_1:0",
            chunk_index=0,
            text="user handbook on refunds and returns policy",
            memory_id="mem_live_1",
            owner_id="user_1",
            agent_id="agent_1",
            memory_type="semantic",
        )
        payload = MemoryChunkPayload.from_chunk(chunk)
        result = await indexing.index_chunks(
            IndexChunksRequest(
                collection_name="agent_memory",
                chunks=[chunk],
                payloads=[payload],
                retrieval_config={},
            )
        )
        assert result.chunk_count == 1
        assert result.dense_enabled is True

        # The collection was created lazily at 768 with the C4 index profile.
        info = await store.collection_info("agent_memory")
        assert info is not None
        params = info["config"]["params"]
        vectors = params["vectors"]
        assert isinstance(vectors, dict)
        assert vectors["size"] == 768
        hnsw = info["config"].get("hnsw_config", {})
        assert hnsw.get("m") == 16
        assert hnsw.get("ef_construct") == 100
        assert hnsw.get("full_scan_threshold") == 10000
        optimizers = info["config"].get("optimizer_config", {})
        assert optimizers.get("indexing_threshold") == 2000

        # The dense query ``memory.lookup`` runs returns the indexed hit.
        query_vector = await embedding.encode("where do I return this purchase?")
        hits = await store.search(
            collection_name="agent_memory",
            query_vector=query_vector,
            query_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="owner_id",
                        match=models.MatchValue(value="user_1"),
                    ),
                    models.FieldCondition(
                        key="agent_id",
                        match=models.MatchValue(value="agent_1"),
                    ),
                ]
            ),
            limit=5,
        )
        assert hits, "bge-768 memory lookup should return the indexed message"
        assert hits[0].payload["memory_id"] == "mem_live_1"
    finally:
        await embedding.shutdown()
        await store.close()
