"""Unit coverage for examples/test_client helpers."""

from __future__ import annotations

import json
from pathlib import Path

import grpc
import pytest

from examples.test_client import test_2
from examples.test_client.test_client import (
    RagTestClient,
    RagTestClientConfig,
    require_ingest_response,
    require_ingest_status_response,
    require_search_response,
)
from shared.transport.grpc.generated import retrieval_service_pb2


class _NotFoundRpcError(grpc.RpcError):
    def code(self) -> grpc.StatusCode:
        return grpc.StatusCode.NOT_FOUND


class _EventuallyVisibleStatusStub:
    def __init__(self) -> None:
        self.calls = 0

    async def GetIngestJobStatus(self, request, *, timeout):
        del timeout
        self.calls += 1
        if self.calls == 1:
            raise _NotFoundRpcError()
        return retrieval_service_pb2.GetIngestJobStatusResponse(
            job_id=request.job_id,
            status="completed",
            doc_id="doc-1",
        )


def test_config_from_env_supports_local_and_remote_targets() -> None:
    config = RagTestClientConfig.from_env(
        {
            "RAG_TEST_GRPC_TARGET": "rag.example.com:443",
            "RAG_TEST_GRPC_SECURE": "true",
            "RAG_TEST_PROJECT_ID": "remote_project",
            "RAG_TEST_USER_ID": "remote_user",
            "RAG_TEST_KB_ID": "remote_kb",
            "RAG_TEST_DOC_ID": "remote_doc",
            "RAG_TEST_COLLECTION_VERSION": "v9",
            "RAG_TEST_TIMEOUT_SECONDS": "12.5",
            "RAG_TEST_INCLUDE_SHARED": "false",
            "RAG_TEST_METADATA": json.dumps({"source": "pytest"}),
        }
    )

    assert config.grpc_target == "rag.example.com:443"
    assert config.grpc_secure is True
    assert config.project_id == "remote_project"
    assert config.user_id == "remote_user"
    assert config.kb_id == "remote_kb"
    assert config.doc_id == "remote_doc"
    assert config.collection_name == "rag_remote_project_v9"
    assert config.timeout_seconds == 12.5
    assert config.include_shared is False
    assert config.metadata == {"source": "pytest"}


def test_config_from_env_allows_collection_override() -> None:
    config = RagTestClientConfig.from_env(
        {
            "RAG_TEST_PROJECT_ID": "demo",
            "RAG_TEST_COLLECTION_NAME": "custom_collection",
        }
    )

    assert config.collection_name == "custom_collection"


def test_builds_grpc_ingest_request_with_raw_text_metadata() -> None:
    client = RagTestClient(
        RagTestClientConfig(
            project_id="p1",
            user_id="u1",
            kb_id="kb",
            doc_id="doc",
            metadata={"source": "unit"},
        )
    )

    request = client.build_ingest_request(
        doc_id="doc-2",
        text="hello world",
        source_uri="memory://doc-2",
        metadata={"kind": "showcase"},
    )

    assert request.project_id == "p1"
    assert request.user_id == "u1"
    assert request.kb_id == "kb"
    assert request.doc_id == "doc-2"
    assert request.source_uri == "memory://doc-2"
    assert request.content_type == "text/plain"
    assert request.metadata["raw_text"] == "hello world"
    assert request.metadata["source"] == "unit"
    assert request.metadata["kind"] == "showcase"


def test_builds_grpc_search_request() -> None:
    client = RagTestClient(
        RagTestClientConfig(
            project_id="p1",
            user_id="u1",
            kb_id="kb",
            include_shared=False,
        )
    )

    request = client.build_search_request(query="hello", kb_ids=("kb1", "kb2"))

    assert request.project_id == "p1"
    assert request.user_id == "u1"
    assert request.query == "hello"
    assert tuple(request.kb_ids) == ("kb1", "kb2")
    assert request.include_shared is False


def test_invalid_metadata_env_must_be_json_object() -> None:
    with pytest.raises(ValueError, match="RAG_TEST_METADATA"):
        RagTestClientConfig.from_env({"RAG_TEST_METADATA": "[]"})


def test_ingest_response_validation_rejects_empty_success() -> None:
    with pytest.raises(RuntimeError, match="job_id"):
        require_ingest_response({"job_id": "", "status": ""})


def test_ingest_response_validation_accepts_broker_first_task_status() -> None:
    require_ingest_response({"job_id": "task-1", "status": "accepted"})
    require_ingest_response({"job_id": "task-1", "status": "queued"})
    require_ingest_status_response({"job_id": "task-1", "status": "queued"}, expected_job_id="task-1")


def test_ingest_status_validation_rejects_mismatched_job_id() -> None:
    with pytest.raises(RuntimeError, match="mismatch"):
        require_ingest_status_response(
            {"job_id": "task-2", "status": "completed"},
            expected_job_id="task-1",
        )


def test_search_response_validation_can_require_chunks() -> None:
    require_search_response({"chunks": [{"text": "answer"}], "elapsed_ms": 1})
    with pytest.raises(RuntimeError, match="chunks"):
        require_search_response({"chunks": []}, require_chunks=True)


@pytest.mark.asyncio
async def test_wait_for_ingest_status_tolerates_initial_not_found() -> None:
    stub = _EventuallyVisibleStatusStub()
    client = RagTestClient(RagTestClientConfig(), grpc_stub=stub)

    status = await client.wait_for_ingest_status(
        "task-1",
        poll_seconds=0,
        max_attempts=3,
    )

    assert status["status"] == "completed"
    assert stub.calls == 2


def test_test_2_writes_loadable_local_source(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    source_uri = test_2._write_local_source("doc/1", "real document text")

    source_path = Path(source_uri)
    assert source_path.is_absolute()
    assert source_path.exists()
    assert source_path.read_text(encoding="utf-8") == "real document text"
    assert source_path.parent.name == "test_client"
