from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from retrieval_service.adapters import (
    AdapterNotFoundError,
    DuplicateAdapterError,
    ProjectAdapter,
    ProjectAdapterRegistry,
    ProjectAdapterResolver,
)
from configs import (
    ProjectConfigNotFoundError,
    SQLiteProjectConfigRepository,
)
from retrieval_service.schema import (
    BaseChunk,
    BaseChunkPayload,
    BaseDocument,
    BaseProjectConfig,
    BaseQueryScope,
    BaseRetrievalFilter,
    DEFAULT_KB_ID,
    Visibility,
)


class ModelsTest(unittest.TestCase):
    def test_project_config_builds_collection_name(self) -> None:
        config = BaseProjectConfig(
            project_id="project_a",
            project_type="website",
            active_embedding_version="v1",
            embedding_model="bge-base",
            reranker_model="bge-reranker-base",
        )

        self.assertEqual(config.collection_name, "rag_project_a_v1")

    def test_project_config_requires_core_fields(self) -> None:
        with self.assertRaisesRegex(ValueError, "project_id is required"):
            BaseProjectConfig(
                project_id=" ",
                project_type="website",
                active_embedding_version="v1",
                embedding_model="bge-base",
                reranker_model="bge-reranker-base",
            )

    def test_retrieval_filter_includes_shared_user_when_scope_allows(self) -> None:
        scope = BaseQueryScope(
            project_id="project_a",
            user_id="user_a",
            kb_ids=("kb_a",),
            include_shared=True,
        )

        retrieval_filter = BaseRetrievalFilter.from_scope(scope)

        self.assertEqual(retrieval_filter.project_id, "project_a")
        self.assertEqual(retrieval_filter.allowed_user_ids, ("user_a", "__shared__"))
        self.assertEqual(retrieval_filter.kb_ids, ("kb_a",))

    def test_retrieval_filter_excludes_shared_user_when_scope_disallows(self) -> None:
        scope = BaseQueryScope(
            project_id="project_a",
            user_id="user_a",
            include_shared=False,
        )

        retrieval_filter = BaseRetrievalFilter.from_scope(scope)

        self.assertEqual(retrieval_filter.allowed_user_ids, ("user_a",))

    def test_blank_kb_id_defaults_to_shared_default(self) -> None:
        document = BaseDocument(
            project_id="project_a",
            user_id="user_a",
            kb_id=" ",
            doc_id="doc_a",
            source_uri="s3://doc",
            content_type="text/plain",
        )

        chunk = BaseChunk(
            project_id="project_a",
            user_id="user_a",
            kb_id="",
            doc_id="doc_a",
            chunk_id="chunk_a",
            chunk_index=0,
            text="hello",
        )

        self.assertEqual(document.kb_id, DEFAULT_KB_ID)
        self.assertEqual(chunk.kb_id, DEFAULT_KB_ID)
        self.assertEqual(BaseChunkPayload.from_chunk(chunk).kb_id, DEFAULT_KB_ID)

    def test_blank_search_kb_ids_are_ignored(self) -> None:
        scope = BaseQueryScope(
            project_id="project_a",
            user_id="user_a",
            kb_ids=(" ", "", "kb_a"),
        )

        self.assertEqual(scope.kb_ids, ("kb_a",))

    def test_chunk_payload_converts_to_qdrant_payload(self) -> None:
        chunk = BaseChunk(
            project_id="project_a",
            user_id="user_a",
            kb_id="kb_a",
            doc_id="doc_a",
            chunk_id="chunk_a",
            chunk_index=0,
            text="hello",
            metadata={"section": "intro"},
        )

        payload = BaseChunkPayload.from_chunk(chunk).to_qdrant_payload()

        self.assertEqual(payload["project_id"], "project_a")
        self.assertEqual(payload["user_id"], "user_a")
        self.assertEqual(payload["data_type"], "document")
        self.assertEqual(payload["visibility"], "private")
        self.assertEqual(payload["chunker_version"], "v1")
        self.assertEqual(payload["metadata"], {"section": "intro"})

    def test_chunk_payload_preserves_text_first_fields(self) -> None:
        chunk = BaseChunk(
            project_id="project_a",
            user_id="user_a",
            kb_id="kb_a",
            doc_id="run_1",
            chunk_id="run_1:0",
            chunk_index=0,
            text="User ran 5.2 km.",
            data_type="running_record",
            visibility=Visibility.SHARED,
            content_hash="abc123",
            embedding_version="embed_v2",
            chunker_version="chunk_v3",
        )

        payload = BaseChunkPayload.from_chunk(chunk).to_qdrant_payload()

        self.assertEqual(payload["data_type"], "running_record")
        self.assertEqual(payload["visibility"], "shared")
        self.assertEqual(payload["content_hash"], "abc123")
        self.assertEqual(payload["embedding_version"], "embed_v2")
        self.assertEqual(payload["chunker_version"], "chunk_v3")

    def test_invalid_visibility_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "visibility must be one of"):
            BaseDocument(
                project_id="project_a",
                user_id="user_a",
                kb_id="kb_a",
                doc_id="doc_a",
                source_uri="s3://doc",
                content_type="text/plain",
                visibility="public",
            )

    def test_chunk_requires_non_negative_index(self) -> None:
        with self.assertRaisesRegex(ValueError, "chunk_index must be non-negative"):
            BaseChunk(
                project_id="project_a",
                user_id="user_a",
                kb_id="kb_a",
                doc_id="doc_a",
                chunk_id="chunk_a",
                chunk_index=-1,
                text="hello",
            )


class ProjectAdapterRegistryTest(unittest.TestCase):
    def test_registry_returns_registered_adapter(self) -> None:
        adapter = DummyAdapter()
        registry = ProjectAdapterRegistry()

        registry.register(adapter)

        self.assertIs(registry.get("Website"), adapter)
        self.assertTrue(registry.has("website"))
        self.assertEqual(registry.project_types(), ("website",))

    def test_registry_rejects_duplicate_project_type(self) -> None:
        registry = ProjectAdapterRegistry()
        registry.register(DummyAdapter())

        with self.assertRaises(DuplicateAdapterError):
            registry.register(DummyAdapter())

    def test_registry_raises_for_missing_adapter(self) -> None:
        registry = ProjectAdapterRegistry()

        with self.assertRaises(AdapterNotFoundError):
            registry.get("website")


class SQLiteProjectConfigRepositoryTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.db_path = Path(self.tempdir.name) / "config.db"
        self.repository = SQLiteProjectConfigRepository(self.db_path)
        await self.repository.initialize()

    async def test_project_config_round_trips(self) -> None:
        config = BaseProjectConfig(
            project_id="project_a",
            project_type="website",
            active_embedding_version="v1",
            embedding_model="bge-base",
            reranker_model="bge-reranker-base",
            chunker_config={"chunk_size": 800},
            retrieval_config={"top_k": 20},
            cache_config={"ttl_seconds": 3600},
        )

        await self.repository.upsert_project(config)
        loaded = await self.repository.get_project_config("project_a")

        self.assertEqual(loaded, config)
        self.assertEqual(await self.repository.get_project_type("project_a"), "website")

    async def test_set_active_embedding_version(self) -> None:
        await self.repository.upsert_project(
            BaseProjectConfig(
                project_id="project_a",
                project_type="website",
                active_embedding_version="v1",
                embedding_model="bge-base",
                reranker_model="bge-reranker-base",
            )
        )

        await self.repository.set_active_embedding_version("project_a", "v2")
        loaded = await self.repository.get_project_config("project_a")

        self.assertEqual(loaded.active_embedding_version, "v2")
        self.assertEqual(loaded.collection_name, "rag_project_a_v2")

    async def test_missing_project_raises(self) -> None:
        with self.assertRaises(ProjectConfigNotFoundError):
            await self.repository.get_project_config("missing")

    async def test_resolver_loads_project_type_and_returns_adapter(self) -> None:
        await self.repository.upsert_project(
            BaseProjectConfig(
                project_id="project_a",
                project_type="website",
                active_embedding_version="v1",
                embedding_model="bge-base",
                reranker_model="bge-reranker-base",
            )
        )
        adapter = DummyAdapter()
        registry = ProjectAdapterRegistry()
        registry.register(adapter)
        resolver = ProjectAdapterResolver(
            project_types=self.repository,
            registry=registry,
        )

        resolved = await resolver.resolve("project_a")

        self.assertIs(resolved, adapter)


class DummyAdapter(ProjectAdapter):
    project_type = "website"

    async def get_config(self, project_id: str) -> BaseProjectConfig:
        return BaseProjectConfig(
            project_id=project_id,
            project_type=self.project_type,
            active_embedding_version="v1",
            embedding_model="bge-base",
            reranker_model="bge-reranker-base",
        )

    async def build_query_scope(self, request: Any) -> BaseQueryScope:
        return BaseQueryScope(
            project_id=request["project_id"],
            user_id=request["user_id"],
        )

    async def build_retrieval_filter(
        self, scope: BaseQueryScope
    ) -> BaseRetrievalFilter:
        return BaseRetrievalFilter.from_scope(scope)

    async def parse_document(self, input_data: Any) -> BaseDocument:
        return BaseDocument(
            project_id=input_data["project_id"],
            user_id=input_data["user_id"],
            kb_id=input_data["kb_id"],
            doc_id=input_data["doc_id"],
            source_uri=input_data["source_uri"],
            content_type=input_data["content_type"],
        )

    async def build_chunks(self, document: BaseDocument) -> list[BaseChunk]:
        return [
            BaseChunk(
                project_id=document.project_id,
                user_id=document.user_id,
                kb_id=document.kb_id,
                doc_id=document.doc_id,
                chunk_id=f"{document.doc_id}:0",
                chunk_index=0,
                text="dummy",
            )
        ]

    async def build_payload(self, chunk: BaseChunk) -> BaseChunkPayload:
        return BaseChunkPayload.from_chunk(chunk)

    async def build_prompt(
        self,
        query: str,
        chunks: list[BaseChunkPayload],
        scope: BaseQueryScope,
    ) -> str:
        return f"{query}\n{scope.project_id}\n{len(chunks)}"


if __name__ == "__main__":
    unittest.main()
