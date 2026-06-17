"""Shared contract tests."""

from __future__ import annotations

import unittest

from shared.contracts import (
    DataType,
    QueuedIngestCommand,
    data_type_spec,
    normalize_data_type,
)


class DataTypeContractTest(unittest.TestCase):
    def test_normalizes_blank_to_project_document(self) -> None:
        self.assertEqual(normalize_data_type(None), DataType.PROJECT_DOCUMENT)
        self.assertEqual(normalize_data_type(""), DataType.PROJECT_DOCUMENT)

    def test_rejects_unknown_data_type(self) -> None:
        with self.assertRaises(ValueError):
            normalize_data_type("unknown")

    def test_registry_marks_reserved_types(self) -> None:
        memory = data_type_spec("agent_memory")
        workflow = data_type_spec("workflow_log")

        self.assertFalse(memory.executable)
        self.assertEqual(memory.owner_service, "memory_service")
        self.assertFalse(workflow.executable)
        self.assertEqual(workflow.owner_service, "workflow_log_service")


class QueuedIngestCommandTest(unittest.TestCase):
    def test_parses_nested_manager_payload(self) -> None:
        command = QueuedIngestCommand.from_queue_payload(
            {
                "request_id": "req1",
                "response_topic": "ingestion.requests.responses.req1",
                "request": {
                    "project_id": "p1",
                    "user_id": "u1",
                    "kb_id": "kb",
                    "doc_id": "d1",
                    "source_uri": "memory://d1",
                    "content_type": "text/plain",
                    "raw_text": "hello",
                    "metadata": {"data_type": "project_document", "source": "test"},
                },
            },
            fallback_request_id="fallback",
        )

        self.assertEqual(command.request_id, "req1")
        self.assertEqual(command.response_topic, "ingestion.requests.responses.req1")
        self.assertEqual(command.project_id, "p1")
        self.assertEqual(command.doc_id, "d1")
        self.assertEqual(command.raw_text, "hello")
        self.assertEqual(command.metadata["data_type"], "project_document")
        self.assertEqual(command.request_payload()["raw_text"], "hello")
        self.assertEqual(command.job_metadata()["request_id"], "req1")

    def test_parses_flat_legacy_payload(self) -> None:
        command = QueuedIngestCommand.from_queue_payload(
            {
                "project_id": "p1",
                "user_id": "u1",
                "kb_id": "kb",
                "doc_id": "d1",
                "source_uri": "memory://d1",
                "metadata": {},
            },
            fallback_request_id="job1",
        )

        self.assertEqual(command.request_id, "job1")
        self.assertEqual(command.response_topic, "")
        self.assertEqual(command.metadata["data_type"], "project_document")


if __name__ == "__main__":
    unittest.main()
