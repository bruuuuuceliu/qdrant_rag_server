# Ingestion Job Acceptance

Section status: superseded by the completed generic ingestion indexing path.

Current note: ingestion now always owns queued job records, runs generic
preparation, and completes successful queued jobs from retrieval indexing
responses. The compatibility project-document client delegation described below
was removed from the enabled ingestion worker path.

## Requirement Document

The ingestion queue consumer currently receives manager-published ingest
messages and immediately delegates execution to the compatibility
`ProjectDocumentClient`. Durable job state exists in `ingestion_service.jobs`,
but the queued worker path does not create an ingestion-owned job record before
the compatibility execution starts. That leaves job acceptance owned by the
project/RAG compatibility path instead of the ingestion service boundary.

This section makes queued ingestion acceptance explicit and ingestion-owned.
The manager and worker continue to use the existing request/response queue
bridge, and execution still delegates to the compatibility project-document
client until the next section moves parsing/chunking/index command production
into ingestion-owned code.

Scope:

- Add a transport-neutral queued ingest command contract.
- Parse manager queue payloads into that command in the ingestion consumer.
- Create a pending ingestion job record before delegated execution starts.
- Return the ingestion-owned job ID in the response envelope.
- Keep direct manager ingest behavior and existing compatibility execution
  unchanged.
- Keep configs under `configs/` and docs under `docs/`.

Out of scope:

- Replacing `ProjectDocumentClient.ingest` execution in the consumer.
- Publishing retrieval indexing commands.
- Adding retry, dead-letter, visibility timeout, or production broker semantics.
- Changing the public gRPC API.

## Acceptance Criteria

- `shared.contracts` exposes a queued ingest command type with request ID,
  response topic, project/user/KB/doc identifiers, source URI, content type,
  metadata, and optional inline raw content.
- The manager queue payload can be parsed by the shared command type without
  importing project-service schemas.
- `IngestionRequestConsumer` accepts an optional `IngestionJobRepository`.
- When a repository is configured, the consumer creates a pending job record
  before calling the compatibility project-document client.
- The job record stores project/user/KB/doc/data type metadata and the source
  URI from the queued command.
- The queue response uses the ingestion-owned job ID while preserving existing
  status and error behavior.
- Existing worker setup remains compatible when no repository is provided.
- Tests cover command parsing, job creation before delegation, response job ID,
  and the no-repository compatibility path.
- `progress.md` records the section result.

## Structure Design

Files changed in this section:

```text
shared/contracts/
  ingest.py          queued command DTO and parser
  __init__.py        public exports

ingestion_service/server/
  consumer.py        command parsing and job acceptance

tests/
  test_shared_contracts.py
  test_ingestion_service_server.py

docs/
  design/ingestion-job-acceptance.md

progress.md
```

No new config file is required. The repository is injected into the consumer by
composition roots and tests; production wiring can be added when the standalone
ingestion worker starts owning execution end to end.

## Class Design

### `QueuedIngestCommand`

Transport-neutral command for one queued ingest request.

Fields:

- `request_id`
- `response_topic`
- `project_id`
- `user_id`
- `kb_id`
- `doc_id`
- `source_uri`
- `content_type`
- `metadata`
- `raw_text`
- `raw_content`

Methods:

- `request_payload() -> dict[str, Any]`: returns the compatibility ingest
  mapping passed to the current project-document client.
- `job_metadata() -> dict[str, Any]`: returns durable job metadata owned by
  ingestion.
- `from_queue_payload(payload, fallback_request_id) -> QueuedIngestCommand`:
  accepts the existing manager payload shape and legacy flat message shape.

### `IngestionRequestConsumer`

Constructor accepts an optional `jobs` repository. When present, message
processing creates an `IngestionJob` with status `pending` before compatibility
execution begins.

## Implementation Design

1. Add `QueuedIngestCommand` and parser helpers to `shared.contracts.ingest`.
2. Export the command from `shared.contracts`.
3. Update `IngestionRequestConsumer` to parse queue payloads through the command
   type.
4. Add optional job repository injection to the consumer.
5. Create a pending `IngestionJob` before delegated compatibility execution.
6. Return the accepted job ID in the response payload while preserving the
   delegated status and error mapping.
7. Add focused tests for command parsing and consumer job acceptance.
8. Run shared-contract, ingestion-server, manager, and ingestion-job tests.

## Review Checklist

- The shared command remains transport-neutral and does not import project,
  retrieval, parser, Qdrant, or engine internals.
- The consumer owns job acceptance but keeps compatibility execution isolated.
- Job creation happens before the delegated `ingest` call.
- Existing queue message shapes continue to work.
- The section stops before adding retrieval indexing worker complexity.
