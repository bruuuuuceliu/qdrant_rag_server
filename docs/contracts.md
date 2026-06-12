# Contracts

## Manager Routing

The implemented route contract lives in `manager_service.routing`.

Inputs:

- `operation`: `ingest`, `search`, `delete`, or `status`
- `data_type`: `project_document`, `agent_memory`, or `workflow_log`
- optional project/user/KB identifiers

Output:

- `target_service`
- whether the route is executable now
- whether async queueing is required
- queue topic when applicable
- reason for reserved routes

## Local Service Clients

Manager dispatch uses the `ProjectDocumentClient` protocol in
`manager_service.clients`.

Current local adapters:

- `project_service.client.LocalProjectServiceClient`: wraps project gateway
  planning and local engine execution for `ingest`, `search`, `delete_document`,
  and `ingest_status`

This is intentionally an in-process compatibility client. Future gRPC or
queue-backed clients should keep the same manager-facing methods so routing
logic does not depend on transport details.

## Queue Messages

The local queue contract lives in `shared.queue`.

Message shape:

```python
QueueMessage(
    topic="ingestion.requests",
    key="project:user:doc",
    payload={...},
    headers={"correlation_id": "..."},
)
```

The local backend is intentionally small and bounded. Future Kafka/Redpanda
adapters should preserve the same topic/key/headers/payload semantics.

## Ingestion Request Queue

Queued ingest requests use the `ingestion.requests` topic.

The local `ingestion_service.server` consumer expects the message payload to be
an ingest request mapping accepted by `project_service.gateway.IngestRequest`.
It delegates to the project-document client boundary so future queue-backed
manager dispatch can reuse the same request shape.

The local manager app uses a request/response bridge:

- request topic: `ingestion.requests`
- response topic: `ingestion.requests.responses.<request_id>`
- request payload: `{request_id, response_topic, request}`
- response payload: `{request_id, ok, result, error}`

Ingestion service settings are loaded from `configs.ingestion`:

- `INGESTION_SERVICE_ENABLED`
- `INGESTION_SERVICE_NAME`
- `INGESTION_REQUEST_TOPIC`
- `INGESTION_WORKER_COUNT`
- `INGESTION_QUEUE_MAXSIZE`
- `INGESTION_JOB_DB_PATH`

## Ingest Lifecycle Events

Ingest lifecycle events use the shared queue contract.

Default topic:

- `ingestion.events`

Configured by:

- `RAG_INGEST_EVENT_TOPIC`
- `RAG_INGEST_EVENT_QUEUE_MAXSIZE`

Events are best-effort and must not fail the ingest job when publishing fails.

Payload fields:

- `event`: `ingest_scheduled`, `ingest_running`, `ingest_completed`, or
  `ingest_failed`
- `job_id`
- `status`: `pending`, `running`, `completed`, or `failed`
- `project_id`, `user_id`, `kb_id`, `doc_id`, `data_type`
- `content_hash`, `raw_storage_key`, `error`

Headers include `project_id`, `user_id`, and `correlation_id` set to the job ID.

The local `workflow_log_service` consumes these events from `ingestion.events`
and records them in a repository. The current durable backend is SQLite,
configured by `WORKFLOW_LOG_DB_PATH`; the consumer is enabled by
`WORKFLOW_LOG_SERVICE_ENABLED`.

## Ingestion Jobs

Durable ingestion job state is owned by `ingestion_service.jobs`.

Current local backend:

- SQLite table: `ingestion_jobs`
- configured by `RAG_INGEST_JOB_DB_PATH`
- bounded queue size configured by `RAG_INGEST_QUEUE_MAXSIZE`

Persisted job fields include:

- `job_id`
- `project_id`
- `user_id`
- `kb_id`
- `doc_id`
- `source_uri`
- `data_type`
- `status`
- `error`
- `content_hash`
- `metadata_json`
- `created_at`
- `updated_at`

When the ingest queue is full, scheduling fails fast and the created job is
marked `failed` with `ingest queue is full`.

`RAG_INGEST_WORKERS` must be at least `1` in runtime configuration. Direct unit
tests may still construct search-only engines with zero workers, but app
configuration rejects deployments that would accept ingest jobs without workers.

Once indexing succeeds, post-index bookkeeping failures are not allowed to mark
the job `failed`. Metadata update, completion-status update, cache
invalidation, and lifecycle event publication are logged independently.

## Retrieval Facade

The retrieval facade lives in `retrieval_service.retrieval`.

Current operations:

- search project-document chunks with dense, sparse, hybrid, optional rerank,
  cache lookup/write, and project/user/KB/doc filters
- delete a document from Qdrant, raw object storage, and retrieval caches
- read raw document bytes from object storage

Project service code should call the facade instead of reaching into retrievers,
Qdrant search, cache invalidation, or raw object storage directly.

Document delete invalidates retrieval caches after Qdrant deletion succeeds,
even if raw object-storage cleanup fails. Optional lexical indexes receive the
same delete through the retrieval facade.

## Indexing Facade

The indexing facade lives in `retrieval_service.indexing`.

Current operation:

- index prepared chunks into dense or hybrid retrieval backends

The request carries collection name, neutral chunks, retrieval payloads, and
retrieval configuration. The facade owns embedding calls, sparse encoding, NER
metadata enrichment, and Qdrant upsert selection.

## Current Compatibility Boundary

The public gRPC `RagService` remains active while internal services are split.
New code should prefer canonical service packages rather than adding more logic
to compatibility shims under `server/`.
