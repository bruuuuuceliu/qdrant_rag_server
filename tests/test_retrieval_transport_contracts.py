"""Retrieval transport contract tests."""

from __future__ import annotations

import unittest

from retrieval_service.retrieval import (
    RetrievalDeleteDocumentCommand,
    RetrievalFilterSpec,
    RetrievalRawDocumentCommand,
    RetrievalResponseEnvelope,
    RetrievalSearchCommand,
    RetrievalSearchResult,
    raw_document_result_to_mapping,
    search_result_to_mapping,
)


class RetrievalTransportContractsTest(unittest.TestCase):
    def test_search_command_parses_envelope_and_converts_to_service_request(self) -> None:
        retrieval_filter = _Filter(project_id="p1", allowed_user_ids=("u1",))
        command = RetrievalSearchCommand.from_payload(
            {
                "request_id": "req-1",
                "response_topic": "retrieval.responses.req-1",
                "request": {
                    "project_id": "p1",
                    "user_id": "u1",
                    "query": "hello",
                    "collection_name": "rag_p1_v1",
                    "retrieval_config": {"top_k": 3},
                    "retrieval_filter": retrieval_filter,
                    "cache_key": "cache-1",
                    "placement_plan": {
                        "placement_version": 4,
                        "targets": [{"shard_id": "retrieval-01"}],
                    },
                },
            },
            fallback_request_id="fallback",
        )

        request = command.to_service_request()

        self.assertEqual(command.request_id, "req-1")
        self.assertEqual(command.response_topic, "retrieval.responses.req-1")
        self.assertEqual(command.request_payload()["query_text"], "hello")
        self.assertEqual(request.project_id, "p1")
        self.assertEqual(request.user_id, "u1")
        self.assertEqual(request.query_text, "hello")
        self.assertEqual(request.collection_name, "rag_p1_v1")
        self.assertEqual(request.retrieval_config, {"top_k": 3})
        self.assertIs(request.retrieval_filter, retrieval_filter)
        self.assertEqual(request.cache_key, "cache-1")
        self.assertEqual(request.placement_plan["placement_version"], 4)

    def test_search_command_accepts_direct_payload(self) -> None:
        retrieval_filter = _Filter(project_id="p1", allowed_user_ids=("u1",))

        command = RetrievalSearchCommand.from_payload(
            {
                "project_id": "p1",
                "user_id": "u1",
                "query_text": "hello",
                "collection_name": "rag_p1_v1",
                "retrieval_filter": retrieval_filter,
            },
            fallback_request_id="fallback",
        )

        self.assertEqual(command.request_id, "fallback")
        self.assertEqual(command.to_service_request().query_text, "hello")

    def test_search_command_normalizes_mapping_filter(self) -> None:
        command = RetrievalSearchCommand.from_payload(
            {
                "project_id": "p1",
                "user_id": "u1",
                "query_text": "hello",
                "collection_name": "rag_p1_v1",
                "retrieval_filter": {
                    "project_id": "p1",
                    "allowed_user_ids": ["u1", "__shared__"],
                    "kb_ids": ["kb"],
                    "doc_ids": ["d1"],
                },
            },
            fallback_request_id="fallback",
        )

        retrieval_filter = command.to_service_request().retrieval_filter

        self.assertIsInstance(retrieval_filter, RetrievalFilterSpec)
        self.assertEqual(retrieval_filter.project_id, "p1")
        self.assertEqual(retrieval_filter.allowed_user_ids, ("u1", "__shared__"))
        self.assertEqual(retrieval_filter.kb_ids, ("kb",))
        self.assertEqual(retrieval_filter.doc_ids, ("d1",))
        self.assertEqual(
            command.request_payload()["retrieval_filter"],
            {
                "project_id": "p1",
                "allowed_user_ids": ["u1", "__shared__"],
                "kb_ids": ["kb"],
                "doc_ids": ["d1"],
            },
        )

    def test_filter_spec_accepts_user_id_as_allowed_user_fallback(self) -> None:
        spec = RetrievalFilterSpec.from_mapping(
            {
                "project_id": "p1",
                "user_id": "u1",
            }
        )

        self.assertEqual(spec.allowed_user_ids, ("u1",))

    def test_filter_spec_validates_required_fields(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "retrieval_filter.project_id, retrieval_filter.allowed_user_ids",
        ):
            RetrievalFilterSpec.from_mapping({})

    def test_search_command_validates_required_fields(self) -> None:
        command = RetrievalSearchCommand.from_payload(
            {
                "project_id": "p1",
                "user_id": "u1",
                "query_text": "",
                "collection_name": "rag_p1_v1",
            },
            fallback_request_id="req-1",
        )

        with self.assertRaisesRegex(
            ValueError,
            "missing required retrieval fields: query_text, retrieval_filter",
        ):
            command.to_service_request()

    def test_delete_command_parses_and_converts_to_service_request(self) -> None:
        command = RetrievalDeleteDocumentCommand.from_payload(
            {
                "request_id": "req-2",
                "request": {
                    "project_id": "p1",
                    "user_id": "u1",
                    "kb_id": "kb",
                    "doc_id": "d1",
                    "collection_name": "rag_p1_v1",
                    "placement_plan": {
                        "placement_version": 5,
                        "targets": [{"shard_id": "retrieval-02"}],
                    },
                },
            },
            fallback_request_id="fallback",
        )

        request = command.to_service_request()

        self.assertEqual(command.request_payload()["doc_id"], "d1")
        self.assertEqual(request.project_id, "p1")
        self.assertEqual(request.user_id, "u1")
        self.assertEqual(request.kb_id, "kb")
        self.assertEqual(request.doc_id, "d1")
        self.assertEqual(request.collection_name, "rag_p1_v1")
        self.assertEqual(request.placement_plan["placement_version"], 5)

    def test_delete_command_validates_required_fields(self) -> None:
        command = RetrievalDeleteDocumentCommand.from_payload(
            {
                "project_id": "p1",
                "user_id": "u1",
                "kb_id": "kb",
                "collection_name": "rag_p1_v1",
            },
            fallback_request_id="req-2",
        )

        with self.assertRaisesRegex(ValueError, "doc_id"):
            command.to_service_request()

    def test_raw_document_command_parses_and_converts_to_service_request(self) -> None:
        command = RetrievalRawDocumentCommand.from_payload(
            {
                "request_id": "req-3",
                "response_topic": "retrieval.responses.req-3",
                "request": {
                    "project_id": "p1",
                    "user_id": "u1",
                    "doc_id": "d1",
                },
            },
            fallback_request_id="fallback",
        )

        request = command.to_service_request()

        self.assertEqual(command.response_topic, "retrieval.responses.req-3")
        self.assertEqual(command.request_payload()["doc_id"], "d1")
        self.assertEqual(request.project_id, "p1")
        self.assertEqual(request.user_id, "u1")
        self.assertEqual(request.doc_id, "d1")

    def test_response_envelope_serializes_success_and_failure(self) -> None:
        success = RetrievalResponseEnvelope.success(
            request_id="req-1",
            result={"deleted": True},
        )
        failure = RetrievalResponseEnvelope.failure(
            request_id="req-2",
            code="validation_error",
            message="doc_id is required",
        )

        self.assertEqual(
            success.to_mapping(),
            {"request_id": "req-1", "ok": True, "result": {"deleted": True}},
        )
        self.assertEqual(
            failure.to_mapping(),
            {
                "request_id": "req-2",
                "ok": False,
                "error": {
                    "code": "validation_error",
                    "message": "doc_id is required",
                    "retryable": False,
                },
            },
        )

    def test_result_mapping_helpers_serialize_facade_results(self) -> None:
        search_result = RetrievalSearchResult(
            chunks=[{"text": "answer", "score": 0.8}],
            elapsed_ms=12,
            cache_hit=True,
        )

        self.assertEqual(
            search_result_to_mapping(search_result),
            {
                "chunks": [{"text": "answer", "score": 0.8}],
                "elapsed_ms": 12,
                "cache_hit": True,
            },
        )
        self.assertEqual(
            raw_document_result_to_mapping(b"raw"),
            {"found": True, "content_b64": "cmF3", "encoding": "base64"},
        )
        self.assertEqual(
            raw_document_result_to_mapping(None),
            {"found": False, "content_b64": "", "encoding": "base64"},
        )


class _Filter:
    def __init__(self, *, project_id: str, allowed_user_ids: tuple[str, ...]) -> None:
        self.project_id = project_id
        self.allowed_user_ids = allowed_user_ids


if __name__ == "__main__":
    unittest.main()
