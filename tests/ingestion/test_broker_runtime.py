"""Broker ingestion runtime tests."""

from __future__ import annotations

import pytest

from ingestion_service.jobs import MemoryIngestionJobRepository
from ingestion_service.server import BrokerIngestionApp
from ingestion_service.service import IngestionService


@pytest.mark.asyncio
async def test_broker_ingestion_app_prepares_index_request() -> None:
    jobs = MemoryIngestionJobRepository()
    app = BrokerIngestionApp(jobs=jobs, ingestion_service=IngestionService())

    result = await app.start_ingest(
        {
            "request_id": "job-1",
            "project_id": "p1",
            "user_id": "u1",
            "kb_id": "kb",
            "doc_id": "d1",
            "source_uri": "memory://d1",
            "content_type": "text/plain",
            "raw_text": "broker raw text",
            "metadata": {
                "collection_name": "rag_p1_v1",
                "placement_plan": {"placement_version": 1},
            },
        }
    )

    assert result["ok"] is True
    assert result["job_id"] == "job-1"
    assert result["status"] == "running"
    assert result["index_request"]["collection_name"] == "rag_p1_v1"
    assert result["index_request"]["chunks"][0]["text"] == "broker raw text"
    assert result["storage_request"] == {
        "operation": "put",
        "key": "p1/u1/d1",
        "value": "broker raw text",
    }
    job = await jobs.get("job-1")
    assert job is not None
    assert job.status.value == "running"
    assert job.metadata["prepared_chunk_count"] == 1


@pytest.mark.asyncio
async def test_broker_ingestion_app_marks_job_failed_on_validation_error() -> None:
    jobs = MemoryIngestionJobRepository()
    app = BrokerIngestionApp(jobs=jobs, ingestion_service=IngestionService())

    result = await app.start_ingest(
        {
            "request_id": "job-1",
            "project_id": "p1",
            "user_id": "u1",
            "kb_id": "kb",
            "doc_id": "d1",
            "source_uri": "memory://d1",
            "content_type": "text/plain",
            "raw_text": "broker raw text",
        }
    )

    assert result["ok"] is False
    assert result["status"] == "failed"
    assert "collection_name" in result["error"]
    job = await jobs.get("job-1")
    assert job is not None
    assert job.status.value == "failed"
