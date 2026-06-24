"""Retrieval HTTP transport tests."""

from __future__ import annotations

import json
import unittest

from retrieval_service.server import RetrievalHttpRequest, create_http_app


class RetrievalHttpServerTest(unittest.IsolatedAsyncioTestCase):
    async def test_health_returns_ok_json(self) -> None:
        app = create_http_app(api=_RetrievalApi())

        response = await app.handle(RetrievalHttpRequest(method="GET", path="/health"))

        self.assertEqual(response.status, 200)
        self.assertEqual(_json(response), {"ok": True})

    async def test_search_dispatches_to_retrieval_api(self) -> None:
        api = _RetrievalApi()
        app = create_http_app(api=api)

        response = await app.handle(
            RetrievalHttpRequest(
                method="POST",
                path="/search",
                body=json.dumps(
                    {
                        "request_id": "req-search",
                        "request": {
                            "project_id": "p1",
                            "user_id": "u1",
                            "query_text": "hello",
                        },
                    }
                ).encode("utf-8"),
            )
        )

        self.assertEqual(response.status, 200)
        self.assertEqual(
            _json(response),
            {
                "request_id": "req-search",
                "ok": True,
                "result": {"chunks": [{"text": "answer"}], "elapsed_ms": 5},
            },
        )
        self.assertEqual(api.search_payload["request"]["query_text"], "hello")
        self.assertEqual(api.search_fallback_request_id, "req-search")

    async def test_invalid_json_returns_validation_error(self) -> None:
        app = create_http_app(api=_RetrievalApi())

        response = await app.handle(
            RetrievalHttpRequest(method="POST", path="/search", body=b"{")
        )

        payload = _json(response)
        self.assertEqual(response.status, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "validation_error")

    async def test_validation_envelope_maps_to_bad_request(self) -> None:
        app = create_http_app(api=_RetrievalApi(mode="validation_error"))

        response = await app.handle(
            RetrievalHttpRequest(
                method="POST",
                path="/documents/delete",
                body=json.dumps({"request_id": "req-delete"}).encode("utf-8"),
            )
        )

        self.assertEqual(response.status, 400)
        self.assertEqual(_json(response)["error"]["code"], "validation_error")

    async def test_unknown_route_returns_not_found_envelope(self) -> None:
        app = create_http_app(api=_RetrievalApi())

        response = await app.handle(
            RetrievalHttpRequest(method="POST", path="/missing", body=b"{}")
        )

        payload = _json(response)
        self.assertEqual(response.status, 404)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "not_found")

    async def test_api_exception_returns_internal_error_envelope(self) -> None:
        app = create_http_app(api=_RetrievalApi(mode="raise"))

        response = await app.handle(
            RetrievalHttpRequest(
                method="POST",
                path="/documents/raw",
                body=json.dumps({"request_id": "req-raw"}).encode("utf-8"),
            )
        )

        payload = _json(response)
        self.assertEqual(response.status, 500)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["request_id"], "req-raw")
        self.assertEqual(payload["error"]["code"], "internal_error")


class _RetrievalApi:
    def __init__(self, *, mode: str = "ok") -> None:
        self.mode = mode
        self.search_payload = None
        self.search_fallback_request_id = None

    async def search(self, payload, *, fallback_request_id: str):
        self.search_payload = payload
        self.search_fallback_request_id = fallback_request_id
        return {
            "request_id": fallback_request_id,
            "ok": True,
            "result": {"chunks": [{"text": "answer"}], "elapsed_ms": 5},
        }

    async def delete_document(self, payload, *, fallback_request_id: str):
        if self.mode == "validation_error":
            return {
                "request_id": fallback_request_id,
                "ok": False,
                "error": {
                    "code": "validation_error",
                    "message": "missing field",
                    "retryable": False,
                },
            }
        return {"request_id": fallback_request_id, "ok": True, "result": {}}

    async def get_raw_document(self, payload, *, fallback_request_id: str):
        if self.mode == "raise":
            raise RuntimeError("raw lookup failed")
        return {"request_id": fallback_request_id, "ok": True, "result": {}}


def _json(response) -> dict:
    return json.loads(response.body.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
