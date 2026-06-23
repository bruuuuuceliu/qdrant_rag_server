# Service Boundaries

Each service is an independently deployable server or worker with its own
top-level workspace. A service may not import another service's internal
modules, repositories, handlers, runtime objects, or implementation details.

There must be no shared parent classes, base service classes, inherited server
frameworks, or cross-service runtime abstractions between servers. Shared code
is limited to stable contracts, schemas, protocol clients, and generic utilities
that do not control server behavior.

Local development must use the same service boundaries as production. Local
means all servers run on the local machine; it does not mean embedded services,
in-memory communication, file-based service communication, or SQLite/local queue
broker substitutes. Redpanda is the runtime broker target and all node-to-node
communication must go through it. The direct exceptions are client to manager
public API calls, manager to Redis task-status lookup by `task_id`, and a
service to its owned private database/storage.

## Manager Service

Owns public API/authentication. It validates the caller, validates the request
envelope, assigns correlation/task IDs, and publishes authenticated task intake
messages to the broker.

The manager must not directly call or trigger project, workflow, ingestion,
retrieval, storage, or other service internals. Existing typed service clients
from `manager_service.clients` are compatibility migration paths and must be
replaced by task intake publication plus Redis task-status reads by `task_id`.

Current project-document operations routed through the client boundary are
legacy relative to the corrected topology: `ingest`, `search`, `delete`, and
`status`.

Target route publication:

| operation | data_type | target |
| --- | --- | --- |
| ingest | project_document | broker task intake topic for task manager dispatch |
| search | project_document | broker task intake topic for task manager dispatch |
| delete | project_document | broker task intake topic for task manager dispatch |
| status | project_document | Redis task-status lookup by `task_id` |

Reserved routes:

| data_type | target |
| --- | --- |
| agent_memory | memory_service |
| workflow_log | workflow_log_service |

Reserved routes validate intent but are not executable yet.

## Project Service

Owns project configuration, project adapters, scope rules, user/KB visibility,
and project-specific request planning. It is a domain task server that consumes
task-manager-issued project-document commands from the broker, gets
project-related information, and publishes project plans/info results through
the broker.

It should not own Qdrant operations, document parsing, storage execution, or
task lifecycle aggregation. During the compatibility phase it may still use
retrieval/ingestion adapters, but those are migration scaffolding.

The project service can run as its own process, but the current remote path
still includes compatibility behavior. Delete remains local-only until the
physical project task API has an explicit delete/status contract.

Current local project-document execution has a project-owned task surface for
ingest, search, status, and delete. This must move behind broker consumption of
task-manager commands and broker publication of project plans/info so the
project service is no longer a direct manager-facing executor or helper-work
dispatcher.

Project planning now also creates optional retrieval placement plans from the
local placement resolver. These plans are message metadata for the retrieval
capability boundary. They do not mean the project service owns Qdrant endpoint
selection.

## Ingestion Service

Owns source fetch, MIME/extension routing, parsing, text cleanup, section/page
metadata, chunking, and ingest job state. Workers should produce neutral chunks
and either call retrieval indexing or publish an indexing request.

The ingestion service is a helper node. It owns the `ingestion.requests` broker
consumer and must run as a standalone worker/server in both local and production
runtime modes. Embedded manager/project ingestion execution is compatibility
scaffolding and is not allowed in the target architecture. Workers prepare
content generically and publish prepared chunks/results back to the broker.

Current queued ingestion creates ingestion-owned job records, runs
`IngestionService.process(...)` for preparation metadata, and publishes prepared
chunks to `retrieval.index.requests`. Ingestion waits for the retrieval index
worker response and marks the ingestion-owned job completed or failed from that
result. Compatibility project-document execution is no longer part of the
ingestion worker path.

If the queued request metadata contains `placement_plan`, ingestion forwards it
unchanged to the retrieval index request. Ingestion does not compute database
placement.

Runtime config must provide at least one ingest worker. A successful indexing
operation is treated as the durable document-write point: metadata, completion
status, cache invalidation, and event publishing failures are logged but do not
convert the already-indexed job to `failed`.

## Workflow Log Service

Workflow logging is a domain service. It consumes workflow-log requests and
service lifecycle events from Redpanda and records them as workflow log entries.
It owns its own service app, repository, and consumer lifecycle. SQLite may be
the local durable database node, but it must not be used as the service broker.

## Task Manager Service

The task manager owns task lifecycle, coordination, domain dispatch, helper
dispatch, fan-out/fan-in state, status, and final task result aggregation. It
consumes manager task intake events, publishes domain commands, consumes domain
plans/info, publishes helper commands, consumes task events and helper results
from the broker, persists task state, writes task status to Redis by `task_id`,
and publishes final result events back to the broker when needed.

The manager/auth service reads task status directly from Redis by `task_id` for
client status checks. Completed task statuses must have TTLs so Redis does not
grow without bound. Domain services and helper nodes should publish lifecycle
events instead of mutating Redis or task-manager state directly.

## Retrieval Service

Owns embedding providers, sparse encoders, Qdrant operations, retrieval modes,
ranking, cache invalidation, raw backup access, indexing/upsert behavior, and
collection versions.

Retrieval is a helper node in the corrected topology. It consumes retrieval or
index commands from the broker and publishes results/events back to the broker.
It should not be called directly by manager or project service internals.

Current internal facades:

- `retrieval_service.retrieval.RetrievalService` owns search, delete, cache
  cleanup, raw-document reads, and optional lexical-index deletes.
- `retrieval_service.indexing.IndexingService` owns embedding, sparse-vector,
  entity-enrichment, and Qdrant upsert for prepared chunks.
- `retrieval_service.indexing.RetrievalIndexConsumer` consumes local
  `retrieval.index.requests` messages and delegates to `IndexingService`.

Placement status:

- `retrieval_service.placement` owns routing-key construction, weighted
  rendezvous assignment, shard records, and placement records.
- Local project planning can resolve placement plans and pass them through
  retrieval/index contracts.
- Retrieval indexing resolves placement write targets to Qdrant stores and
  writes primary plus replica targets.
- Retrieval search uses placement read targets for bucket fanout, primary-first
  replica failover, shard-local retriever construction, score merge, and
  placement-scoped cache keys.
- Retrieval delete resolves placement write targets and deletes dense/sparse
  records from each target before cache invalidation.
- Routing policies and versioned placement records are persisted in the
  placement registry, including explicit moving/stale/active rebalance states.
- Data migration/reindex orchestration remains outside the current implemented
  runtime. Production broker retry/dead-letter behavior is intentionally out of
  scope for now.

## Shared Code

Allowed in `shared`:

- queue protocols
- transport-neutral message DTOs
- protocol clients
- correlation IDs and common error codes
- stable schemas that are true cross-service contracts

Not allowed in `shared`:

- parent service classes or inherited server frameworks
- server lifecycle/runtime abstractions
- Qdrant implementations
- parsers
- project adapters
- embedding clients
- orchestration/business logic

## Config And Test Ownership

Service-specific config must live in service folders under `configs/`, for
example `configs/manager/`, `configs/project/`, `configs/ingestion/`,
`configs/retrieval/`, `configs/workflow_log/`, `configs/broker/`, and
`configs/sqlite/`.

Service-specific tests must live in matching folders under `tests/`, for
example `tests/manager/`, `tests/project/`, `tests/ingestion/`,
`tests/retrieval/`, `tests/workflow_log/`, and `tests/broker/`.
Cross-service tests belong under `tests/integration/` and must exercise public
APIs or broker topics rather than importing service internals across folders.
