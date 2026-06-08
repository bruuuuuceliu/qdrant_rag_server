"""Phase 5 tests: object storage and full ingestion pipeline with storage."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from retrieval_service.storage import (
    FilesystemObjectStorage,
    MemoryObjectStorage,
    ObjectStorageError,
    make_storage_key,
)
from retrieval_service.engine import RagEngine
from retrieval_service.core.models import BaseDocument, BaseChunk
from retrieval_service.core.models import BaseProjectConfig
from retrieval_service.adapters import ProjectAdapter


class MemoryObjectStorageTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.storage = MemoryObjectStorage()

    async def test_put_and_get_round_trip(self) -> None:
        await self.storage.put("key1", b"hello world", "text/plain")
        result = await self.storage.get("key1")
        self.assertEqual(result, b"hello world")

    async def test_get_missing_raises(self) -> None:
        with self.assertRaises(ObjectStorageError):
            await self.storage.get("missing")

    async def test_exists_returns_true_for_stored(self) -> None:
        await self.storage.put("key1", b"data")
        self.assertTrue(await self.storage.exists("key1"))

    async def test_exists_returns_false_for_missing(self) -> None:
        self.assertFalse(await self.storage.exists("missing"))

    async def test_delete_removes_object(self) -> None:
        await self.storage.put("key1", b"data")
        await self.storage.delete("key1")
        self.assertFalse(await self.storage.exists("key1"))

    async def test_make_storage_key(self) -> None:
        key = make_storage_key("p1", "u1", "d1")
        self.assertEqual(key, "p1/u1/d1")


class FilesystemObjectStorageTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.storage = FilesystemObjectStorage(self.tempdir.name)

    async def test_put_creates_file(self) -> None:
        await self.storage.put("docs/doc1.txt", b"content")
        self.assertTrue(await self.storage.exists("docs/doc1.txt"))

    async def test_get_reads_file(self) -> None:
        await self.storage.put("doc.txt", b"hello")
        result = await self.storage.get("doc.txt")
        self.assertEqual(result, b"hello")

    async def test_delete_removes_file(self) -> None:
        await self.storage.put("doc.txt", b"hello")
        await self.storage.delete("doc.txt")
        self.assertFalse(await self.storage.exists("doc.txt"))


class EngineIngestWithStorageTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.adapter = MagicMock(spec=ProjectAdapter)
        self.adapter.project_type = "test"

    async def test_ingest_stores_raw_document_in_storage(self) -> None:
        storage = MemoryObjectStorage()

        self.adapter.parse_document = AsyncMock(
            return_value=BaseDocument(
                project_id="p1", user_id="u1", kb_id="kb_a",
                doc_id="d1", source_uri="https://ex.com",
                content_type="text/html",
                metadata={"raw_text": "Document content here"},
            )
        )
        self.adapter.build_chunks = AsyncMock(
            return_value=[
                BaseChunk(
                    project_id="p1", user_id="u1", kb_id="kb_a",
                    doc_id="d1", chunk_id="c1", chunk_index=0,
                    text="Document content here",
                )
            ]
        )
        self.adapter.build_payload = AsyncMock()

        embed_fn = MagicMock()
        embed_fn.encode_batch = AsyncMock(return_value=[[0.1] * 768])

        engine = RagEngine(
            embed_fn=embed_fn,
            qdrant_store=AsyncMock(),
            object_storage=storage,
            ingest_worker_count=1,
        )

        from retrieval_service.gateway import IngestRequest, IngestPlan
        from retrieval_service.core.models import BaseProjectConfig

        plan = IngestPlan(
            request=IngestRequest(
                project_id="p1", user_id="u1", kb_id="kb_a",
                doc_id="d1", source_uri="https://ex.com",
                content_type="text/html",
                metadata={"raw_text": "Document content here"},
            ),
            adapter=self.adapter,
            config=BaseProjectConfig(
                project_id="p1", project_type="test",
                active_embedding_version="v1",
                embedding_model="bge-base",
                reranker_model="bge-reranker-base",
            ),
        )

        await engine.schedule_ingest(plan)
        await asyncio.sleep(0.2)

        storage_key = make_storage_key("p1", "u1", "d1")
        stored = await storage.get(storage_key)
        self.assertEqual(stored, b"Document content here")

        await engine.shutdown()

    async def test_delete_document_removes_from_storage(self) -> None:
        storage = MemoryObjectStorage()
        storage_key = make_storage_key("p1", "u1", "d1")
        await storage.put(storage_key, b"raw content")

        engine = RagEngine(
            embed_fn=AsyncMock(),
            qdrant_store=AsyncMock(),
            object_storage=storage,
        )

        config = BaseProjectConfig(
            project_id="p1",
            project_type="test",
            active_embedding_version="v1",
            embedding_model="bge-base",
            reranker_model="bge-reranker-base",
        )
        await engine.delete_document(
            config=config,
            user_id="u1",
            kb_id="kb_a",
            doc_id="d1",
        )

        self.assertFalse(await storage.exists(storage_key))
        engine._qdrant_store.delete_document.assert_called_once_with(
            collection_name="rag_p1_v1",
            project_id="p1",
            user_id="u1",
            kb_id="kb_a",
            doc_id="d1",
        )

        await engine.shutdown()

    async def test_get_raw_document_retrieves_from_storage(self) -> None:
        storage = MemoryObjectStorage()
        storage_key = make_storage_key("p1", "u1", "d1")
        await storage.put(storage_key, b"raw content")

        engine = RagEngine(
            embed_fn=AsyncMock(),
            qdrant_store=AsyncMock(),
            object_storage=storage,
        )

        content = await engine.get_raw_document(
            project_id="p1", user_id="u1", doc_id="d1"
        )
        self.assertEqual(content, b"raw content")

    async def test_get_raw_document_returns_none_when_missing(self) -> None:
        storage = MemoryObjectStorage()
        engine = RagEngine(
            embed_fn=AsyncMock(),
            qdrant_store=AsyncMock(),
            object_storage=storage,
        )
        content = await engine.get_raw_document(
            project_id="p1", user_id="u1", doc_id="missing"
        )
        self.assertIsNone(content)

    async def test_ingest_without_storage_still_works(self) -> None:
        self.adapter.parse_document = AsyncMock(
            return_value=BaseDocument(
                project_id="p1", user_id="u1", kb_id="kb_a",
                doc_id="d1", source_uri="https://ex.com",
                content_type="text/html",
            )
        )
        self.adapter.build_chunks = AsyncMock(
            return_value=[
                BaseChunk(
                    project_id="p1", user_id="u1", kb_id="kb_a",
                    doc_id="d1", chunk_id="c1", chunk_index=0,
                    text="hello",
                )
            ]
        )
        self.adapter.build_payload = AsyncMock()

        embed_fn = MagicMock()
        embed_fn.encode_batch = AsyncMock(return_value=[[0.1] * 768])

        engine = RagEngine(
            embed_fn=embed_fn,
            qdrant_store=AsyncMock(),
            ingest_worker_count=1,
        )

        from retrieval_service.gateway import IngestRequest, IngestPlan
        from retrieval_service.core.models import BaseProjectConfig

        plan = IngestPlan(
            request=IngestRequest(
                project_id="p1", user_id="u1", kb_id="kb_a",
                doc_id="d1", source_uri="https://ex.com",
                content_type="text/html",
            ),
            adapter=self.adapter,
            config=BaseProjectConfig(
                project_id="p1", project_type="test",
                active_embedding_version="v1",
                embedding_model="bge-base",
                reranker_model="bge-reranker-base",
            ),
        )

        result = await engine.schedule_ingest(plan)
        self.assertIsNotNone(result.job_id)

        await asyncio.sleep(0.2)
        await engine.shutdown()


if __name__ == "__main__":
    unittest.main()
