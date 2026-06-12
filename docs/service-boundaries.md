# Service Boundaries

## Manager Service

Owns public request routing. It decides which service should handle an operation
based on operation and `data_type`.

The manager depends on typed service clients from `manager_service.clients`,
not on concrete gateway or engine internals. The current clients are local
in-process adapters; network-backed clients should preserve the same narrow
methods.

Current project-document operations routed through the client boundary:
`ingest`, `search`, `delete`, and `status`.

Current executable routes:

| operation | data_type | target |
| --- | --- | --- |
| ingest | project_document | ingestion_service |
| search | project_document | retrieval_service |
| delete | project_document | retrieval_service |
| status | project_document | ingestion_service |

Reserved routes:

| data_type | target |
| --- | --- |
| agent_memory | memory_service |
| workflow_log | workflow_log_service |

Reserved routes validate intent but are not executable yet.

## Project Service

Owns project configuration, project adapters, scope rules, user/KB visibility,
and project-specific request planning. It should not own Qdrant operations or
document parsing long term. During the compatibility phase it may construct and
inject retrieval-service facades, but engine behavior should stay at
orchestration and DTO mapping.

## Ingestion Service

Owns source fetch, MIME/extension routing, parsing, text cleanup, section/page
metadata, chunking, and ingest job state. Workers should produce neutral chunks
and either call retrieval indexing or publish an indexing request.

The ingestion service also owns the local `ingestion.requests` queue consumer
used during migration. It delegates queued project-document requests through the
project-document client boundary rather than importing manager internals.

Runtime config must provide at least one ingest worker. A successful indexing
operation is treated as the durable document-write point: metadata, completion
status, cache invalidation, and event publishing failures are logged but do not
convert the already-indexed job to `failed`.

## Workflow Log Service

Consumes ingest lifecycle events from the local queue and records them as
workflow log entries. It owns its own service app, repository, and consumer
lifecycle. SQLite is the current durable backend during the migration away from
in-process-only execution.

## Retrieval Service

Owns embedding providers, sparse encoders, Qdrant operations, retrieval modes,
ranking, cache invalidation, raw backup access, indexing/upsert behavior, and
collection versions.

Current internal facades:

- `retrieval_service.retrieval.RetrievalService` owns search, delete, cache
  cleanup, raw-document reads, and optional lexical-index deletes.
- `retrieval_service.indexing.IndexingService` owns embedding, sparse-vector,
  entity-enrichment, and Qdrant upsert for prepared chunks.

## Shared Code

Allowed in `shared`:

- queue protocols
- transport-neutral message DTOs
- internal clients
- correlation IDs and common error codes

Not allowed in `shared`:

- Qdrant implementations
- parsers
- project adapters
- embedding clients
- orchestration/business logic
