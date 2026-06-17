# Contracts

## Manager Routing

The implemented route contract lives in `manager_service.routing`.

Data-type values are defined once in `shared.contracts.data_types`. The shared
registry intentionally contains only route labels, owner service names, and
reserved-state metadata; parsing rules, payload schemas, filters, and indexing
behavior remain in the owning service packages.

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

Manager dispatch now uses service-specific manager-facing protocols in
`manager_service.clients`.

Current local adapters:

- `manager_service.clients.ProjectDocumentIngestionClient`: compatibility
  adapter from `ProjectDocumentClient` to `IngestionClient`
- `manager_service.clients.ProjectDocumentRetrievalClient`: compatibility
  adapter from `ProjectDocumentClient` to `RetrievalClient`
- `project_service.client.ProjectPlannedRetrievalClient`: local adapter that
  uses project gateway planning and retrieval-facade execution for search/delete
- `project_service.client.ProjectPlannedRetrievalApiClient`: local adapter that
  uses project gateway planning and retrieval API server-context execution for
  search/delete
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
It creates an ingestion job record when one is configured, then delegates to
the project-document client boundary so future queue-backed manager dispatch can
reuse the same request shape.

When an ingestion preparation service is configured, the consumer also runs the
source through `IngestionService.process(...)` before delegated compatibility
execution and records preparation metadata on the ingestion job. The metadata is
limited to durable audit fields such as content hash, handler name, prepared
chunk count, raw content length, content type, and chunker versions; prepared
chunk text is not stored in the job table.

`IngestRequest` accepts first-class `raw_text` or `raw_content` fields for
inline content. Legacy metadata keys `raw_text` and `raw_content` remain
supported for compatibility, including the temporary shared gRPC proto whose
ingest request still exposes only string metadata.

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

## Retrieval Transport Contracts

Transport-neutral retrieval API contracts live in
`retrieval_service.retrieval.contracts`. They are intentionally local Python
dataclasses today so future gRPC, HTTP, or queue adapters can reuse the same
payload rules without importing manager or project-service internals.

Current commands:

- `RetrievalFilterSpec`: retrieval-owned project/user/KB/doc filter spec for
  transport payloads; mapping payloads are normalized into this spec at the
  retrieval boundary.
- `RetrievalSearchCommand`: carries project/user/query, collection name,
  retrieval config, retrieval filter, optional cache key, request ID, and
  optional response topic.
- `RetrievalDeleteDocumentCommand`: carries project/user/KB/doc identifiers,
  collection name, request ID, and optional response topic.
- `RetrievalRawDocumentCommand`: carries project/user/doc identifiers, request
  ID, and optional response topic.

Commands accept either direct request mappings or envelopes shaped as:

```python
{
    "request_id": "...",
    "response_topic": "...",
    "request": {...},
}
```

They validate required routing fields before converting into the current
retrieval facade request dataclasses. Responses use
`RetrievalResponseEnvelope` with `{request_id, ok, result, error}`. Raw-document
bytes are serialized as base64 metadata through `raw_document_result_to_mapping`
so transport adapters do not leak Python `bytes` objects into JSON-style
payloads.

`RetrievalApiHandler` is the current transport-neutral dispatch layer. It
accepts plain payload mappings, parses retrieval commands, calls a
`RetrievalAppContext`-compatible object, and returns response-envelope mappings
for search, delete, and raw-document lookup. Validation failures are returned as
non-retryable `validation_error` envelopes; unexpected app failures are returned
as retryable `internal_error` envelopes.

`retrieval_service.server.create_app(retrieval_service=...)` builds a retrieval
API server context around the app context and handler. It exposes async
`search`, `delete_document`, and `get_raw_document` payload methods for future
transport adapters. This is the retrieval-owned service surface.

`retrieval_service.server.create_http_app(api=...)` wraps that API context with a
minimal JSON HTTP adapter for physical retrieval-service deployment. Current
routes are:

- `POST /search`
- `POST /documents/delete`
- `POST /documents/raw`
- `GET /health`

HTTP handlers accept the same command/envelope payloads as the transport-neutral
API. Successful envelopes return `200`, validation errors return `400`, unknown
routes return `404`, and unexpected retrieval failures return structured
`internal_error` envelopes with `500`. The transport is configured through
`configs/retrieval` using `RETRIEVAL_HTTP_HOST`, `RETRIEVAL_HTTP_PORT`, and
`RETRIEVAL_HTTP_READ_TIMEOUT`.

## Retrieval API Queue

Queued retrieval API requests use the `retrieval.api.requests` topic.

`RetrievalApiQueueClient` publishes request envelopes shaped as:

```python
{
    "request_id": "...",
    "response_topic": "retrieval.api.requests.responses.<request_id>",
    "operation": "search",  # search, delete_document, or get_raw_document
    "request": {...},
}
```

`RetrievalApiQueueConsumer` consumes the request, calls the retrieval API server
context, and publishes the response-envelope mapping unchanged to the response
topic. Unknown operations return non-retryable `validation_error` envelopes.
Client-side response timeouts raise `RetrievalApiQueueTimeoutError`.

Manager local composition can select retrieval execution mode with
`MANAGER_RETRIEVAL_CLIENT_MODE`:

- `local`: call the in-process retrieval API server context directly
- `queue`: start an embedded retrieval API queue app and call it through
  `RetrievalApiQueueClient`

Queue mode uses `MANAGER_RETRIEVAL_TOPIC` and
`MANAGER_RETRIEVAL_RESPONSE_TIMEOUT`.

## Indexing Facade

The indexing facade lives in `retrieval_service.indexing`.

Current operation:

- index prepared chunks into dense or hybrid retrieval backends

The request carries collection name, neutral chunks, retrieval payloads, and
retrieval configuration. The facade owns embedding calls, sparse encoding, NER
metadata enrichment, and Qdrant upsert selection.

## Retrieval Index Queue

Queued retrieval indexing requests use the `retrieval.index.requests` topic.

The queue payload is parsed by `RetrievalIndexCommand` in
`retrieval_service.indexing.commands` and converted into an
`IndexChunksRequest` for `IndexingService`. The command carries:

- `request_id`
- `job_id`
- `collection_name`
- `chunks`
- `payloads`
- `retrieval_config`
- optional `response_topic`

Prepared chunks are kept neutral. The queue layer does not own collection
policy, retrieval configuration generation, or payload enrichment beyond
transport serialization.

When the ingestion worker publishes to this queue, it must provide a non-empty
`collection_name`; otherwise the request is rejected as a validation failure.

## Current Compatibility Boundary

The public gRPC `RagService` remains active while internal services are split.
New code should prefer canonical service packages rather than adding more logic
to compatibility shims under `server/`.
