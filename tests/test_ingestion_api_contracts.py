"""Ingestion API contract tests."""

from __future__ import annotations

import unittest

from ingestion_service.schemas import IngestionJob
from ingestion_service.server import (
    IngestionResponseEnvelope,
    IngestionStatusCommand,
    job_to_mapping,
)
from shared.contracts import JobStatus


class IngestionApiContractsTest(unittest.TestCase):
    def test_status_command_parses_direct_payload(self) -> None:
        command = IngestionStatusCommand.from_payload(
            {"request_id": "req1", "job_id": "job1"},
            fallback_request_id="fallback",
        )

        self.assertEqual(command.request_id, "req1")
        self.assertEqual(command.job_id, "job1")

    def test_status_command_parses_request_envelope(self) -> None:
        command = IngestionStatusCommand.from_payload(
            {"request_id": "req1", "request": {"job_id": "job1"}},
            fallback_request_id="fallback",
        )

        self.assertEqual(command.request_id, "req1")
        self.assertEqual(command.job_id, "job1")

    def test_status_command_rejects_missing_job_id(self) -> None:
        with self.assertRaisesRegex(ValueError, "job_id"):
            IngestionStatusCommand.from_payload({}, fallback_request_id="fallback")

    def test_status_command_rejects_non_object_request(self) -> None:
        with self.assertRaisesRegex(ValueError, "request must be an object"):
            IngestionStatusCommand.from_payload(
                {"request": []},
                fallback_request_id="fallback",
            )

    def test_response_envelope_renders_success_and_failure(self) -> None:
        success = IngestionResponseEnvelope.success(
            request_id="req1",
            result={"job_id": "job1"},
        ).to_mapping()
        failure = IngestionResponseEnvelope.failure(
            request_id="req2",
            code="not_found",
            message="missing",
        ).to_mapping()

        self.assertTrue(success["ok"])
        self.assertEqual(success["result"]["job_id"], "job1")
        self.assertFalse(failure["ok"])
        self.assertEqual(failure["error"]["code"], "not_found")

    def test_job_to_mapping_uses_transport_safe_fields(self) -> None:
        job = IngestionJob(
            job_id="job1",
            source_uri="memory://doc",
            document_id="doc1",
            status=JobStatus.RUNNING,
            metadata={"project_id": "p1"},
            created_at=1.0,
            updated_at=2.0,
        )

        payload = job_to_mapping(job)

        self.assertEqual(payload["job_id"], "job1")
        self.assertEqual(payload["status"], JobStatus.RUNNING.value)
        self.assertEqual(payload["doc_id"], "doc1")
        self.assertEqual(payload["metadata"], {"project_id": "p1"})


if __name__ == "__main__":
    unittest.main()
