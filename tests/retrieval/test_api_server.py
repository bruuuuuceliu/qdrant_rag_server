"""Retrieval broker-helper API context tests."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from retrieval_service.retrieval import RetrievalApiHandler, RetrievalSearchResult, create_app
from retrieval_service.server import RetrievalHelperApiContext


class RetrievalHelperApiContextTest(unittest.IsolatedAsyncioTestCase):
    async def test_context_exposes_search_delete_and_raw_payload_methods(self) -> None:
        service = _RetrievalService(raw_document=b"raw")
        app = await create_app(retrieval_service=service)
        context = RetrievalHelperApiContext(
            app=app,
            handler=RetrievalApiHandler(app=app),
        )

        search_response = await context.search(
            {
                "request_id": "req-search",
                "request": {
                    "project_id": "p1",
                    "user_id": "u1",
                    "query_text": "hello",
                    "collection_name": "rag_p1_v1",
                    "retrieval_filter": {
                        "project_id": "p1",
                        "allowed_user_ids": ["u1"],
                    },
                },
            },
            fallback_request_id="fallback-search",
        )
        delete_response = await context.delete_document(
            {
                "project_id": "p1",
                "user_id": "u1",
                "kb_id": "kb",
                "doc_id": "d1",
                "collection_name": "rag_p1_v1",
            },
            fallback_request_id="req-delete",
        )
        raw_response = await context.get_raw_document(
            {
                "project_id": "p1",
                "user_id": "u1",
                "doc_id": "d1",
            },
            fallback_request_id="req-raw",
        )

        self.assertEqual(search_response["request_id"], "req-search")
        self.assertTrue(search_response["ok"])
        self.assertEqual(search_response["result"]["chunks"], [{"text": "answer"}])
        self.assertEqual(delete_response, {"request_id": "req-delete", "ok": True, "result": {"deleted": True}})
        self.assertEqual(
            raw_response,
            {
                "request_id": "req-raw",
                "ok": True,
                "result": {
                    "found": True,
                    "content_b64": "cmF3",
                    "encoding": "base64",
                },
            },
        )
        service.search.assert_awaited_once()
        service.delete_document.assert_awaited_once()
        service.get_raw_document.assert_awaited_once()

    async def test_shutdown_delegates_to_retrieval_service(self) -> None:
        service = _RetrievalService()
        app = await create_app(retrieval_service=service)
        context = RetrievalHelperApiContext(
            app=app,
            handler=RetrievalApiHandler(app=app),
        )

        await context.shutdown()

        service.shutdown.assert_awaited_once()


class _RetrievalService:
    def __init__(self, *, raw_document: bytes | None = None) -> None:
        self.raw_document = raw_document
        self.search = AsyncMock(
            return_value=RetrievalSearchResult(
                chunks=[{"text": "answer"}],
                elapsed_ms=4,
            )
        )
        self.delete_document = AsyncMock(return_value=None)
        self.get_raw_document = AsyncMock(return_value=raw_document)
        self.shutdown = AsyncMock()


if __name__ == "__main__":
    unittest.main()
