from __future__ import annotations

import asyncio
import unittest
from typing import Any

from rag_server.adapters import (
    ProjectAdapter,
    ProjectAdapterRegistry,
    ProjectAdapterResolver,
)
from rag_server.gateway import (
    AsyncConcurrencyLimiter,
    ConcurrencyLimitExceededError,
    IngestPlan,
    InvalidRequestError,
    ProjectScopeMismatchError,
    RagGateway,
    SearchPlan,
)
from rag_server.core.models import (
    BaseChunk,
    BaseChunkPayload,
    BaseDocument,
    BaseProjectConfig,
    BaseQueryScope,
    BaseRetrievalFilter,
    DEFAULT_KB_ID,
)


class RagGatewayTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.project_types = InMemoryProjectTypes({"project_a": "website"})
        self.adapter = GatewayDummyAdapter()
        self.registry = ProjectAdapterRegistry()
        self.registry.register(self.adapter)
        self.gateway = RagGateway(
            adapter_resolver=ProjectAdapterResolver(
                project_types=self.project_types,
                registry=self.registry,
            ),
            concurrency_limiter=AsyncConcurrencyLimiter(
                max_per_project=4,
                max_per_user=2,
            ),
        )

    async def test_prepare_search_builds_enforced_scope_and_filter(self) -> None:
        plan = await self.gateway.prepare_search(
            {
                "project_id": "project_a",
                "user_id": "user_a",
                "query": "What is this?",
                "kb_ids": ["kb_a"],
                "include_shared": True,
            }
        )

        self.assertIsInstance(plan, SearchPlan)
        self.assertIs(plan.adapter, self.adapter)
        self.assertEqual(plan.config.project_id, "project_a")
        self.assertEqual(plan.scope.project_id, "project_a")
        self.assertEqual(plan.scope.user_id, "user_a")
        self.assertEqual(plan.scope.kb_ids, ("kb_a",))
        self.assertEqual(plan.retrieval_filter.allowed_user_ids, ("user_a", "__shared__"))

    async def test_prepare_ingest_validates_and_resolves_adapter(self) -> None:
        plan = await self.gateway.prepare_ingest(
            {
                "project_id": "project_a",
                "user_id": "user_a",
                "kb_id": "kb_a",
                "doc_id": "doc_a",
                "source_uri": "s3://bucket/doc.txt",
                "content_type": "text/plain",
            }
        )

        self.assertIsInstance(plan, IngestPlan)
        self.assertIs(plan.adapter, self.adapter)
        self.assertEqual(plan.config.collection_name, "rag_project_a_v1")

    async def test_prepare_ingest_defaults_missing_kb_id(self) -> None:
        plan = await self.gateway.prepare_ingest(
            {
                "project_id": "project_a",
                "user_id": "user_a",
                "doc_id": "doc_a",
                "source_uri": "s3://bucket/doc.txt",
                "content_type": "text/plain",
            }
        )

        self.assertEqual(plan.request.kb_id, DEFAULT_KB_ID)

    async def test_prepare_ingest_defaults_blank_kb_id(self) -> None:
        plan = await self.gateway.prepare_ingest(
            {
                "project_id": "project_a",
                "user_id": "user_a",
                "kb_id": " ",
                "doc_id": "doc_a",
                "source_uri": "s3://bucket/doc.txt",
                "content_type": "text/plain",
            }
        )

        self.assertEqual(plan.request.kb_id, DEFAULT_KB_ID)

    async def test_search_rejects_client_supplied_raw_filters(self) -> None:
        with self.assertRaisesRegex(
            InvalidRequestError,
            "client-supplied retrieval filters are forbidden",
        ):
            await self.gateway.prepare_search(
                {
                    "project_id": "project_a",
                    "user_id": "user_a",
                    "query": "What is this?",
                    "raw_qdrant_filter": {"must": []},
                }
            )

    async def test_search_rejects_missing_required_scope(self) -> None:
        with self.assertRaisesRegex(InvalidRequestError, "project_id is required"):
            await self.gateway.prepare_search(
                {
                    "project_id": "",
                    "user_id": "user_a",
                    "query": "What is this?",
                }
            )

    async def test_gateway_rejects_adapter_scope_mismatch(self) -> None:
        project_types = InMemoryProjectTypes({"project_a": "website"})
        registry = ProjectAdapterRegistry()
        registry.register(ScopeChangingAdapter())
        gateway = RagGateway(
            adapter_resolver=ProjectAdapterResolver(
                project_types=project_types,
                registry=registry,
            ),
            concurrency_limiter=AsyncConcurrencyLimiter(
                max_per_project=4,
                max_per_user=2,
            ),
        )

        with self.assertRaisesRegex(ProjectScopeMismatchError, "adapter changed user_id"):
            await gateway.prepare_search(
                {
                    "project_id": "project_a",
                    "user_id": "user_a",
                    "query": "What is this?",
                }
            )

    async def test_project_concurrency_limit_returns_saturation_error(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        adapter = GatewayDummyAdapter(started=started, release=release)
        registry = ProjectAdapterRegistry()
        registry.register(adapter)
        gateway = RagGateway(
            adapter_resolver=ProjectAdapterResolver(
                project_types=InMemoryProjectTypes({"project_a": "website"}),
                registry=registry,
            ),
            concurrency_limiter=AsyncConcurrencyLimiter(
                max_per_project=1,
                max_per_user=1,
            ),
        )

        first = asyncio.create_task(
            gateway.prepare_search(
                {
                    "project_id": "project_a",
                    "user_id": "user_a",
                    "query": "First",
                }
            )
        )
        await asyncio.wait_for(started.wait(), timeout=1)

        with self.assertRaises(ConcurrencyLimitExceededError):
            await gateway.prepare_search(
                {
                    "project_id": "project_a",
                    "user_id": "user_b",
                    "query": "Second",
                }
            )

        release.set()
        await first


class InMemoryProjectTypes:
    def __init__(self, project_types: dict[str, str]) -> None:
        self._project_types = project_types

    async def get_project_type(self, project_id: str) -> str:
        return self._project_types[project_id]


class GatewayDummyAdapter(ProjectAdapter):
    project_type = "website"

    def __init__(
        self,
        *,
        started: asyncio.Event | None = None,
        release: asyncio.Event | None = None,
    ) -> None:
        self._started = started
        self._release = release

    async def get_config(self, project_id: str) -> BaseProjectConfig:
        return BaseProjectConfig(
            project_id=project_id,
            project_type=self.project_type,
            active_embedding_version="v1",
            embedding_model="bge-base",
            reranker_model="bge-reranker-base",
        )

    async def build_query_scope(self, request: Any) -> BaseQueryScope:
        if self._started is not None:
            self._started.set()
        if self._release is not None:
            await self._release.wait()
        return BaseQueryScope(
            project_id=request.project_id,
            user_id=request.user_id,
            kb_ids=request.kb_ids,
            include_shared=request.include_shared,
        )

    async def build_retrieval_filter(
        self, scope: BaseQueryScope
    ) -> BaseRetrievalFilter:
        return BaseRetrievalFilter.from_scope(scope)

    async def parse_document(self, input_data: Any) -> BaseDocument:
        return BaseDocument(
            project_id=input_data.project_id,
            user_id=input_data.user_id,
            kb_id=input_data.kb_id,
            doc_id=input_data.doc_id,
            source_uri=input_data.source_uri,
            content_type=input_data.content_type,
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


class ScopeChangingAdapter(GatewayDummyAdapter):
    async def build_query_scope(self, request: Any) -> BaseQueryScope:
        return BaseQueryScope(
            project_id=request.project_id,
            user_id="other_user",
        )


if __name__ == "__main__":
    unittest.main()
