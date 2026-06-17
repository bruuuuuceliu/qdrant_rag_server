# Architecture

The project is moving from one in-process RAG server toward a small set of
physically close services. The current external `RagService` API remains the
compatibility boundary while internal contracts are split.

## Service Map

```text
clients
  -> manager_service
       -> project_service
       -> ingestion_service
       -> retrieval_service
       -> memory_service          future
       -> workflow_log_service    future
```

## Current Ownership

- `manager_service`: route decisions for public requests.
- `project_service`: project config, adapters, scope construction, retrieval filter intent, and current gRPC compatibility app.
- `ingestion_service`: source loading, document routing, parsing, cleaning,
  chunking, neutral ingestion output, and queued ingest request consumption.
- `retrieval_service`: embeddings, Qdrant, BM25/hybrid retrieval, ranking, indexing, cache, storage, and health.
- `workflow_log_service`: lifecycle-event consumer, repository, and local
  service app.
- `shared`: small transport-neutral contracts only.

`memory_service` remains reserved. `workflow_log_service` now provides the
local sink for ingest lifecycle events, durable SQLite storage, and a service
composition root for future independent deployment.

## Communication

Synchronous request/response work should use internal gRPC or typed local
clients during migration:

- manager -> project: resolve config and scope
- manager -> retrieval: search, delete, raw lookup, indexing facade
- manager -> ingestion: ingest status
- local project app -> workflow log service: consume lifecycle events

Current manager dispatch uses service-specific `IngestionClient` and
`RetrievalClient` protocols from `manager_service.clients`. Local manager
composition uses project planning plus retrieval API server-context execution
for search/delete, while ingest/status still keep compatibility execution during
the migration. Remote project/RAG mode continues to adapt
`ProjectDocumentClient` until independent ingestion and retrieval network APIs
are extracted.

Retrieval search, delete, and raw-document calls now have transport-neutral
command and response contracts under `retrieval_service.retrieval.contracts`.
They are not a physical server yet; they define the payload shape future gRPC,
HTTP, or queue adapters should expose around the retrieval facade.
`RetrievalApiHandler` provides the matching transport-neutral dispatch layer:
payload mappings in, retrieval app calls, response-envelope mappings out.
`retrieval_service.server` now provides the retrieval-owned server context that
future network transports can wrap without depending on the compatibility
`RagService` API.
For local split-service development, retrieval API calls can also cross
`retrieval.api.requests` through the shared queue request/response transport.
Manager local mode selects direct in-process or queue-backed retrieval API
execution with `MANAGER_RETRIEVAL_CLIENT_MODE`.

For ingest, the local manager app publishes to `ingestion.requests` and waits on
a per-request response topic. The local ingestion service app consumes the
request, creates an ingestion-owned job record when configured, and delegates
through the project-document client during migration. When configured with a
retrieval queue and collection name, ingestion also publishes prepared chunks to
`retrieval.index.requests`.

Asynchronous work should use queue messages:

- `ingestion.requests`
- `ingestion.events`
- `retrieval.api.requests`
- `retrieval.index.requests`

The current local queue backend is in-process and bounded. It intentionally uses
topic/key/headers/payload message shape so Kafka-compatible brokers can replace
it later without changing domain logic.

## Migration Order

1. Keep external `RagService` stable.
2. Add manager route decisions and internal contracts.
3. Move ingest job ownership and durable status into `ingestion_service`.
4. Extract retrieval indexing/search facades from `project_service.rag`.
5. Move workflow events to queue publishing.
6. Route manager dispatch through service clients instead of gateway/engine
   internals.
7. Remove legacy duplicate schemas and compatibility shims once callers migrate.
