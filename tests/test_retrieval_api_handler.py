"""Retrieval API handler tests."""

from __future__ import annotations

import unittest

from retrieval_service.retrieval import RetrievalApiHandler, RetrievalSearchResult


class RetrievalApiHandlerTest(unittest.IsolatedAsyncioTestCase):
    async def test_handle_search_normalizes_mapping_filter_and_returns_envelope(self) -> None:
        app = _App()
        handler = RetrievalApiHandler(app=app)

        response = await handler.handle_search(
            {
                "request_id": "req-1",
                "request": {
                    "project_id": "p1",
                    "user_id": "u1",
                    "query_text": "hello",
                    "collection_name": "rag_p1_v1",
                    "retrieval_filter": {
                        "project_id": "p1",
                        "allowed_user_ids": ["u1", "__shared__"],
                        "kb_ids": ["kb"],
                    },
                },
            },
            fallback_request_id="fallback",
        )

        self.assertEqual(response["request_id"], "req-1")
        self.assertTrue(response["ok"])
        self.assertEqual(
            response["result"],
            {
                "chunks": [{"text": "answer", "score": 0.8}],
                "elapsed_ms": 7,
                "cache_hit": False,
            },
        )
        self.assertEqual(app.search_request.project_id, "p1")
        self.assertEqual(app.search_request.retrieval_filter.project_id, "p1")
        self.assertEqual(
            app.search_request.retrieval_filter.allowed_user_ids,
            ("u1", "__shared__"),
        )
        self.assertEqual(app.search_request.retrieval_filter.kb_ids, ("kb",))

    async def test_handle_delete_returns_success_envelope(self) -> None:
        app = _App()
        handler = RetrievalApiHandler(app=app)

        response = await handler.handle_delete_document(
            {
                "project_id": "p1",
                "user_id": "u1",
                "kb_id": "kb",
                "doc_id": "d1",
                "collection_name": "rag_p1_v1",
            },
            fallback_request_id="req-2",
        )

        self.assertEqual(
            response,
            {"request_id": "req-2", "ok": True, "result": {"deleted": True}},
        )
        self.assertEqual(app.delete_request.doc_id, "d1")

    async def test_handle_raw_document_returns_base64_envelope(self) -> None:
        app = _App(raw_document=b"raw")
        handler = RetrievalApiHandler(app=app)

        response = await handler.handle_raw_document(
            {
                "project_id": "p1",
                "user_id": "u1",
                "doc_id": "d1",
            },
            fallback_request_id="req-3",
        )

        self.assertEqual(
            response,
            {
                "request_id": "req-3",
                "ok": True,
                "result": {
                    "found": True,
                    "content_b64": "cmF3",
                    "encoding": "base64",
                },
            },
        )
        self.assertEqual(app.raw_request.doc_id, "d1")

    async def test_validation_error_returns_failure_envelope(self) -> None:
        handler = RetrievalApiHandler(app=_App())

        response = await handler.handle_search(
            {
                "request_id": "req-4",
                "request": {
                    "project_id": "p1",
                    "user_id": "u1",
                    "query_text": "",
                    "collection_name": "rag_p1_v1",
                },
            },
            fallback_request_id="fallback",
        )

        self.assertEqual(response["request_id"], "req-4")
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "validation_error")
        self.assertFalse(response["error"]["retryable"])
        self.assertIn("query_text", response["error"]["message"])

    async def test_unexpected_app_error_returns_retryable_failure(self) -> None:
        handler = RetrievalApiHandler(app=_App(error=RuntimeError("store down")))

        response = await handler.handle_delete_document(
            {
                "request_id": "req-5",
                "request": {
                    "project_id": "p1",
                    "user_id": "u1",
                    "kb_id": "kb",
                    "doc_id": "d1",
                    "collection_name": "rag_p1_v1",
                },
            },
            fallback_request_id="fallback",
        )

        self.assertEqual(response["request_id"], "req-5")
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "internal_error")
        self.assertTrue(response["error"]["retryable"])
        self.assertEqual(response["error"]["message"], "store down")


class _App:
    def __init__(self, *, raw_document: bytes | None = None, error: Exception | None = None) -> None:
        self.raw_document = raw_document
        self.error = error

    async def search(self, request):
        if self.error is not None:
            raise self.error
        self.search_request = request
        return RetrievalSearchResult(
            chunks=[{"text": "answer", "score": 0.8}],
            elapsed_ms=7,
        )

    async def delete_document(self, request):
        if self.error is not None:
            raise self.error
        self.delete_request = request
        return None

    async def get_raw_document(self, request):
        if self.error is not None:
            raise self.error
        self.raw_request = request
        return self.raw_document


if __name__ == "__main__":
    unittest.main()
