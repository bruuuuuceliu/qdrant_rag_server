"""Phase 6 tests: website project adapter."""

from __future__ import annotations

import unittest

from rag_server.gateway import SearchRequest, IngestRequest
from rag_server.core.models import (
    BaseChunk,
    BaseDocument,
)
from rag_server.adapters.website import (
    WebsiteChunkPayload,
    WebsiteDocument,
    WebsiteProjectAdapter,
    WebsiteProjectConfig,
)


class WebsiteProjectConfigTest(unittest.TestCase):
    def test_allows_registered_domain(self) -> None:
        config = WebsiteProjectConfig(
            project_id="p1",
            project_type="website",
            active_embedding_version="v1",
            embedding_model="bge-base",
            reranker_model="bge-reranker-base",
            domains=("example.com", "docs.example.com"),
        )
        self.assertTrue(config.allows_domain("example.com"))
        self.assertFalse(config.allows_domain("evil.com"))

    def test_allows_all_when_no_domains_configured(self) -> None:
        config = WebsiteProjectConfig(
            project_id="p1",
            project_type="website",
            active_embedding_version="v1",
            embedding_model="bge-base",
            reranker_model="bge-reranker-base",
        )
        self.assertTrue(config.allows_domain("anything.com"))

    def test_domain_extraction_strips_www(self) -> None:
        adapter = WebsiteProjectAdapter()
        self.assertEqual(adapter.get_domain_from_url("https://www.example.com/page"), "example.com")
        self.assertEqual(adapter.get_domain_from_url("https://docs.example.com"), "docs.example.com")
        self.assertEqual(adapter.get_domain_from_url("invalid"), "")


class WebsiteDocumentTest(unittest.TestCase):
    def test_website_document_fields(self) -> None:
        doc = WebsiteDocument(
            project_id="p1",
            user_id="u1",
            kb_id="kb_a",
            doc_id="d1",
            source_uri="https://example.com",
            content_type="text/html",
            url="https://example.com",
            canonical_url="https://example.com",
            page_title="Home",
            page_description="Welcome page",
        )
        self.assertEqual(doc.url, "https://example.com")
        self.assertEqual(doc.page_title, "Home")
        self.assertEqual(doc.project_id, "p1")

    def test_website_document_is_instance_of_base(self) -> None:
        doc = WebsiteDocument(
            project_id="p1",
            user_id="u1",
            kb_id="kb_a",
            doc_id="d1",
            source_uri="s3://bucket/doc",
            content_type="text/html",
        )
        self.assertIsInstance(doc, BaseDocument)


class WebsiteChunkPayloadTest(unittest.TestCase):
    def test_to_qdrant_payload_includes_website_fields(self) -> None:
        payload = WebsiteChunkPayload(
            project_id="p1",
            user_id="u1",
            kb_id="kb_a",
            doc_id="d1",
            chunk_id="c1",
            chunk_index=0,
            text="hello",
            url="https://example.com",
            canonical_url="https://example.com",
            page_title="Home",
            section_heading="Introduction",
        )
        qdrant_payload = payload.to_qdrant_payload()

        self.assertEqual(qdrant_payload["text"], "hello")
        self.assertEqual(qdrant_payload["url"], "https://example.com")
        self.assertEqual(qdrant_payload["page_title"], "Home")
        self.assertEqual(qdrant_payload["section_heading"], "Introduction")
        self.assertEqual(qdrant_payload["project_id"], "p1")


class WebsiteProjectAdapterTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.adapter = WebsiteProjectAdapter()

    async def test_get_config_returns_website_config(self) -> None:
        config = await self.adapter.get_config("p1")
        self.assertIsInstance(config, WebsiteProjectConfig)
        self.assertEqual(config.project_type, "website")
        self.assertEqual(config.project_id, "p1")

    async def test_build_query_scope_from_search_request(self) -> None:
        request = SearchRequest(
            project_id="p1",
            user_id="u1",
            query="What is X?",
            kb_ids=("kb_a",),
            include_shared=False,
        )
        scope = await self.adapter.build_query_scope(request)
        self.assertEqual(scope.project_id, "p1")
        self.assertEqual(scope.user_id, "u1")
        self.assertEqual(scope.kb_ids, ("kb_a",))
        self.assertFalse(scope.include_shared)

    async def test_build_retrieval_filter_includes_shared_by_default(self) -> None:
        from rag_server.core.models import BaseQueryScope
        scope = BaseQueryScope(project_id="p1", user_id="u1")
        rf = await self.adapter.build_retrieval_filter(scope)
        self.assertEqual(rf.allowed_user_ids, ("u1", "__shared__"))

    async def test_parse_document_builds_website_document(self) -> None:
        request = IngestRequest(
            project_id="p1",
            user_id="u1",
            kb_id="kb_a",
            doc_id="d1",
            source_uri="https://example.com/doc.html",
            content_type="text/html",
            metadata={"raw_text": "Hello world\n\nSecond paragraph"},
        )
        doc = await self.adapter.parse_document(request)
        self.assertIsInstance(doc, WebsiteDocument)
        self.assertEqual(doc.url, "https://example.com/doc.html")
        self.assertEqual(doc.page_title, "https://example.com/doc.html")

    async def test_build_chunks_splits_paragraphs(self) -> None:
        doc = WebsiteDocument(
            project_id="p1",
            user_id="u1",
            kb_id="kb_a",
            doc_id="d1",
            source_uri="https://example.com",
            content_type="text/html",
            metadata={"raw_text": "First paragraph\n\nSecond paragraph\n\nThird"},
        )
        chunks = await self.adapter.build_chunks(doc)
        self.assertEqual(len(chunks), 3)
        self.assertEqual(chunks[0].text, "First paragraph")
        self.assertEqual(chunks[2].text, "Third")

    async def test_build_chunks_fallback_single_chunk(self) -> None:
        doc = BaseDocument(
            project_id="p1",
            user_id="u1",
            kb_id="kb_a",
            doc_id="d1",
            source_uri="simple text",
            content_type="text/plain",
        )
        chunks = await self.adapter.build_chunks(doc)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].text, "simple text")

    async def test_build_payload_includes_website_fields(self) -> None:
        chunk = BaseChunk(
            project_id="p1",
            user_id="u1",
            kb_id="kb_a",
            doc_id="d1",
            chunk_id="d1:0",
            chunk_index=0,
            text="hello",
            metadata={"url": "https://ex.com", "page_title": "T", "section": "Intro"},
        )
        payload = await self.adapter.build_payload(chunk)
        self.assertIsInstance(payload, WebsiteChunkPayload)
        self.assertEqual(payload.url, "https://ex.com")
        self.assertEqual(payload.page_title, "T")
        self.assertEqual(payload.section_heading, "Intro")

    async def test_build_prompt_includes_urls_and_context(self) -> None:
        from rag_server.core.models import BaseQueryScope, BaseChunkPayload
        chunks = [
            WebsiteChunkPayload(
                project_id="p1", user_id="u1", kb_id="kb_a", doc_id="d1",
                chunk_id="c1", chunk_index=0, text="Response text",
                url="https://ex.com", page_title="Page Title",
            )
        ]
        scope = BaseQueryScope(project_id="p1", user_id="u1")
        prompt = await self.adapter.build_prompt("What is X?", chunks, scope)

        self.assertIn("What is X?", prompt)
        self.assertIn("Response text", prompt)
        self.assertIn("Page Title", prompt)
        self.assertIn("https://ex.com", prompt)
        self.assertIn("Answer:", prompt)


if __name__ == "__main__":
    unittest.main()
