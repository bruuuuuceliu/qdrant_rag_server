"""Retrieval HTTP client tests."""

from __future__ import annotations

import unittest

from retrieval_service.server import RetrievalApiHttpClient


class RetrievalApiHttpClientTest(unittest.IsolatedAsyncioTestCase):
    async def test_search_posts_payload_and_returns_envelope(self) -> None:
        http_client = _HttpClient(
            _Response(
                {
                    "request_id": "req-search",
                    "ok": True,
                    "result": {"chunks": [{"text": "answer"}]},
                }
            )
        )
        client = RetrievalApiHttpClient(
            base_url="http://retrieval:8081/",
            http_client=http_client,
        )

        result = await client.search({"request_id": "req-search", "request": {}})

        self.assertEqual(result["request_id"], "req-search")
        self.assertEqual(http_client.url, "http://retrieval:8081/search")
        self.assertEqual(http_client.json_payload["request_id"], "req-search")

    async def test_delete_and_raw_use_expected_routes(self) -> None:
        http_client = _HttpClient(_Response({"request_id": "req", "ok": True}))
        client = RetrievalApiHttpClient(
            base_url="http://retrieval:8081",
            http_client=http_client,
        )

        await client.delete_document({"request_id": "req-delete"})
        delete_url = http_client.url
        await client.get_raw_document({"request_id": "req-raw"})

        self.assertEqual(delete_url, "http://retrieval:8081/documents/delete")
        self.assertEqual(http_client.url, "http://retrieval:8081/documents/raw")

    async def test_non_object_response_raises_clear_error(self) -> None:
        client = RetrievalApiHttpClient(
            base_url="http://retrieval:8081",
            http_client=_HttpClient(_Response(["bad"])),
        )

        with self.assertRaisesRegex(RuntimeError, "must be a JSON object"):
            await client.search({"request_id": "req"})

    async def test_invalid_json_response_raises_clear_error(self) -> None:
        client = RetrievalApiHttpClient(
            base_url="http://retrieval:8081",
            http_client=_HttpClient(_Response(ValueError("bad json"))),
        )

        with self.assertRaisesRegex(RuntimeError, "not valid JSON"):
            await client.search({"request_id": "req"})

    async def test_error_envelope_is_returned_without_status_raise(self) -> None:
        client = RetrievalApiHttpClient(
            base_url="http://retrieval:8081",
            http_client=_HttpClient(
                _Response(
                    {
                        "request_id": "req",
                        "ok": False,
                        "error": {"code": "validation_error", "message": "bad"},
                    },
                    status_code=400,
                )
            ),
        )

        result = await client.search({"request_id": "req"})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "validation_error")


class _HttpClient:
    def __init__(self, response) -> None:
        self.response = response
        self.url = None
        self.json_payload = None

    async def post(self, url: str, *, json):
        self.url = url
        self.json_payload = json
        return self.response


class _Response:
    def __init__(self, payload, *, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def json(self):
        if isinstance(self.payload, ValueError):
            raise self.payload
        return self.payload


if __name__ == "__main__":
    unittest.main()
