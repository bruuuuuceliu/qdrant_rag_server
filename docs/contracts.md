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

Compatibility output:

- `target_service`
- whether the route is executable now
- whether async queueing is required
- queue topic when applicable
- reason for reserved routes

Target output:

- authenticated task intake envelope
- `correlation_id` and `task_id`
- operation and `data_type`
- tenant/project/user/KB identifiers needed by the task manager

In the target runtime, the manager does not publish directly to project,
workflow, ingestion, retrieval, or storage topics. It publishes task intake
messages only. The task manager consumes those messages and dispatches domain
task server commands through Redpanda.

## Service Clients

Manager dispatch now uses service-specific manager-facing protocols in
`manager_service.clients`.

Current compatibility/local adapters:

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

These adapters are migration scaffolding. Target runtime manager code should
publish task intake messages to Redpanda and read Redis task status by
`task_id`; it should not call project/domain/helper service clients directly.
The task manager owns domain and helper command publication.

## Placement Metadata

Project planning can attach an optional `placement_plan` mapping to ingest,
search, delete, and index work. The plan is created from the local placement
resolver and persisted placement registry. It identifies routing keys,
placement version, and target shard IDs.

Current local runtime status:

- `placement_plan` is produced by project planning when placement is enabled.
- Retrieval search/delete and retrieval-index command contracts preserve it.
- Queued ingestion forwards it to retrieval indexing through message metadata.
- Retrieval indexing resolves placement targets to Qdrant stores and writes the
  primary plus configured replica targets.
- Retrieval search groups targets by routing key, searches one target per group,
  falls back from primary to replicas on target failure, and merges bucket hits
  by score.
- Retrieval delete resolves the same placement write set and removes dense and
  sparse records from each target.
- Search cache keys are namespaced by placement version, shard ID, and routing
  key so placement changes do not reuse stale cache entries.
- Routing policies and placement history are persisted with explicit
  moving/stale/active rebalance states.
- Migration/reindex orchestration and network broker semantics remain pending.

## Broker Messages

The message contract currently lives in `shared.queue`, but the runtime broker
target is Redpanda for both local and production.

Message shape:

```python
QueueMessage(
    topic="ingestion.requests",
    key="project:user:doc",
    payload={...},
    headers={"correlation_id": "..."},
)
```

Local/in-memory/SQLite queue backends are compatibility scaffolding. The
Redpanda adapter should preserve the same topic/key/headers/payload semantics.

## Target Broker Topics

Target runtime topics are Redpanda topics. Names may be finalized during
contract implementation, but ownership must follow this direction:

| Topic family | Producer | Consumer | Purpose |
| --- | --- | --- | --- |
| task intake | manager service | task manager | Accepted public requests after auth/validation. |
| domain commands | task manager | project/workflow/memory/other domain services | Trigger domain-specific planning or info lookup. |
| domain results | domain services | task manager | Return scope, policy, plans, query/read results, or errors. |
| helper commands | task manager | ingestion/retrieval/storage/other helper nodes | Execute concrete work. |
| helper results | helper nodes | task manager | Return execution results and lifecycle events. |
| task status/results | task manager | Redis and broker observers | Keep Redis current by `task_id` and publish final result events. |

## Ingestion Request Queue

Queued ingest requests currently use the `ingestion.requests` topic.

This is compatibility scaffolding. In the target runtime, ingestion commands are
published by the task manager after project-domain planning, not by the public
manager or by project service direct calls.

The local `ingestion_service.server` consumer expects the message payload to be
an ingest request mapping accepted by `project_service.gateway.IngestRequest`.
It creates an ingestion-owned job record, runs the source through
`IngestionService.process(...)`, records preparation metadata, and publishes
prepared chunks to `retrieval.index.requests`. Successful queued ingestion is
completed from the retrieval index worker response; compatibility
project-document callback execution is no longer part of the ingestion path.

Preparation metadata is limited to durable audit fields such as content hash,
handler name, prepared chunk count, raw content length, content type, and
chunker versions; prepared chunk text is not stored in the job table.

`IngestRequest` accepts first-class `raw_text` or `raw_content` fields for
inline content. Legacy metadata keys `raw_text` and `raw_content` remain
supported for compatibility, including the temporary shared gRPC proto whose
ingest request still exposes only string metadata.

The local manager app uses a request/response bridge:

- request topic: `ingestion.requests`
- response topic: `ingestion.requests.responses.<request_id>`
- request payload: `{request_id, response_topic, request}`
- response payload: `{request_id, ok, result, error}`

When project planning provides `placement_plan`, queued ingestion carries it in
request metadata and forwards it to the retrieval index queue.

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
  retrieval config, retrieval filter, optional cache key, optional
  `placement_plan`, request ID, and optional response topic.
- `RetrievalDeleteDocumentCommand`: carries project/user/KB/doc identifiers,
  collection name, optional `placement_plan`, request ID, and optional response
  topic.
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
- `placement_plan`
- optional `response_topic`

Prepared chunks are kept neutral. The queue layer does not own collection
policy, retrieval configuration generation, placement assignment, or payload
enrichment beyond transport serialization.

When the ingestion worker publishes to this queue, it must provide a non-empty
`collection_name`; otherwise the request is rejected as a validation failure.

## Current Compatibility Boundary

The public gRPC `RagService` remains active while internal services are split.
New code should prefer canonical service packages rather than adding more logic
to compatibility shims under `server/`.
