"""Retrieval service app context tests."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from retrieval_service.retrieval import create_app


class RetrievalServiceAppTest(unittest.IsolatedAsyncioTestCase):
    async def test_app_delegates_retrieval_operations(self) -> None:
        service = _FakeRetrievalService()
        app = await create_app(retrieval_service=service)

        search_result = await app.search("search-request")
        delete_result = await app.delete_document("delete-request")
        raw_result = await app.get_raw_document("raw-request")

        self.assertEqual(search_result, "search-result")
        self.assertEqual(delete_result, "deleted")
        self.assertEqual(raw_result, b"raw")
        service.search.assert_awaited_once_with("search-request")
        service.delete_document.assert_awaited_once_with("delete-request")
        service.get_raw_document.assert_awaited_once_with("raw-request")

    async def test_shutdown_delegates_when_available(self) -> None:
        service = _FakeRetrievalService()
        app = await create_app(retrieval_service=service)

        await app.shutdown()

        service.shutdown.assert_awaited_once()


class _FakeRetrievalService:
    def __init__(self) -> None:
        self.search = AsyncMock(return_value="search-result")
        self.delete_document = AsyncMock(return_value="deleted")
        self.get_raw_document = AsyncMock(return_value=b"raw")
        self.shutdown = AsyncMock()


if __name__ == "__main__":
    unittest.main()
