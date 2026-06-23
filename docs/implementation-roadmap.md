# Implementation Roadmap

This roadmap tracks the next iterations toward a separated multi-service
retrieval and ingestion platform.

## Iteration 1: Manager Routing Foundation

Status: implemented.

- Add `manager_service` package and route contract.
- Add reserved `memory_service` and `workflow_log_service` packages.
- Add bounded local queue contract under `shared.queue`.
- Add service-specific config namespaces under `configs/`.
- Add architecture, boundary, and contract docs.

## Iteration 2: Durable Ingestion Jobs

Status: implemented.

- Move ingest job ownership toward `ingestion_service/jobs`.
- Replace in-memory-only job status with a durable SQLite repository.
- Add queue saturation behavior with a clear overload error.
- Store job records with project/user/KB/doc/data type/status/error/content hash.
- Keep existing `RagService` ingest/status API working.

## Iteration 3: Retrieval Facade

Status: implemented for search, delete, and raw-document access.

- Add a retrieval-service facade for search, delete, and raw-document operations.
- Shrink `project_service.rag.engine` retrieval paths toward orchestration only.
- Keep Qdrant, embeddings, sparse retrieval, reranking, and cache in
  `retrieval_service`.
- Add facade tests for query construction, scope filters, delete cleanup, and
  compatibility with existing engine behavior.

## Iteration 4: Indexing Facade

Status: implemented.

- Add a retrieval indexing facade for embedding, sparse vectors, entity metadata,
  and Qdrant upsert.
- Inject the indexing facade at the `RagEngine` boundary so project
  orchestration can delegate prepared chunks without owning vector-store
  details.
- Keep ingestion preparation focused on parsing, cleanup, chunking, and raw
  document storage.
- Preserve ingest job lifecycle and public gRPC behavior.
- Add tests for dense indexing, NER metadata enrichment, and hybrid sparse
  upsert delegation.

## Iteration 5: Async Service Events

Status: implemented locally for ingest lifecycle events and workflow-log
consumption; Redpanda runtime transport remains pending.

- Publish ingest/index lifecycle events through `shared.queue`.
- Wire the local app with a bounded `LocalQueueBroker` for `ingestion.events`.
- Keep event publishing best-effort so lifecycle logging does not block ingest.
- Keep retries, leases, attempt counts, backoff, and dead-letter handling out of
  scope for the current broker phase.
- Preserve successful indexing state when post-index metadata, status, cache, or
  event bookkeeping fails.
- Add a local `workflow_log_service` consumer that persists lifecycle events
  from the queue.
- Add a workflow-log service app and SQLite repository so lifecycle logs survive
  process restarts.

## Iteration 6: Manager Local Service Clients

Status: implemented.

- Add a typed manager-facing `ProjectDocumentClient` protocol.
- Add `project_service.client.LocalProjectServiceClient` to compose gateway
  planning with local engine execution behind one project-service boundary.
- Wire manager bootstrap through the project-document client instead of passing
  gateway and engine internals directly.
- Route manager `status` and `delete` operations through the same route/client
  boundary.
- Treat in-process clients as compatibility scaffolding while preserving a
  replacement point for public API or Redpanda-backed clients.
- Add tests for manager routing through the client boundary.

## Iteration 7: Ingestion Request Queue Consumer

Status: implemented locally with multi-process local worker support.

- Add `ingestion_service.server` with an `ingestion.requests` queue consumer.
- Wire the local manager app to publish ingest requests through the queue and
  wait for a per-request response topic.
- Add standalone ingestion worker server mode backed by the current queue
  contract as migration scaffolding.
- Add typed ingestion service settings under `configs/ingestion`.
- Preserve the Kafka-compatible message shape in `shared.queue` so it can be
  backed by Redpanda in local and production runtime.

## Iteration 8: Shared Data-Type Routing Registry

Status: implemented for route labels and reserved-state metadata.

- Add `shared.contracts.data_types` as the canonical source for public
  `data_type` route labels.
- Keep only transport-neutral route metadata in shared code.
- Continue to keep parser selection, payload schema, retrieval filters, and
  indexing behavior inside service-owned packages.
- Wire manager routing through the shared data-type normalizer while preserving
  the existing manager-facing import surface.

## Iteration 9: Remote Project/RAG Service Boundary

Status: implemented for search, ingest, and status; delete is pending proto
support.

- Add `project_service.client.RemoteProjectServiceClient` over the existing
  gRPC transport.
- Add manager configuration for `MANAGER_PROJECT_CLIENT_MODE=local|grpc` and
  `MANAGER_PROJECT_GRPC_TARGET`.
- Earlier ingestion worker project-client settings have been removed; ingestion
  now publishes prepared chunks to retrieval indexing instead of delegating to a
  project-document client.
- Allow local scripts to run manager, project/RAG service, ingestion worker,
  and Qdrant as separate local services with `--split-services`.
- Keep the gRPC contract intentionally narrow and call out delete as unsupported
  remotely until the transport contract is extended.

## Iteration 10: Manager Split Clients And Local Adapters

Status: implemented locally.

- Add manager-facing `IngestionClient` and `RetrievalClient` protocols.
- Keep `ProjectDocumentClient` as a compatibility adapter during extraction.
- Wire manager bootstrap through explicit ingestion and retrieval clients.
- Add local ingestion and retrieval adapters for split-client composition.
- Add an import-boundary guard so manager core does not import service
  implementation internals.

## Iteration 11: Ingestion-Owned Preparation And Index Publication

Status: implemented locally with compatibility execution still active.

- Parse queued ingest messages into a shared `QueuedIngestCommand`.
- Create ingestion-owned job records before delegated compatibility execution.
- Run `IngestionService.process(...)` in the worker to record preparation
  metadata.
- Optionally publish prepared chunks to `retrieval.index.requests` when a
  retrieval queue and collection name are configured.
- Validate indexing publication inputs before enqueueing retrieval work.

## Iteration 12: Retrieval Index Queue Worker

Status: implemented locally.

- Add `RetrievalIndexCommand` as the queue DTO for prepared chunk indexing.
- Add `RetrievalIndexConsumer` to call `IndexingService.index_chunks(...)`.
- Add a retrieval indexing app context for injected queue/indexing-service
  composition.
- Validate retrieval index commands at the retrieval queue boundary.

## Iteration 13: Retrieval App Context And Boundary Guards

Status: implemented locally.

- Add a retrieval service app context for injected search, delete, and raw
  document operations.
- Add local manager ingestion and retrieval adapters for split-client
  composition.
- Add import-boundary guards for manager core, ingestion server queue modules,
  and retrieval indexing queue modules.
- Keep compatibility composition roots explicitly allowed while physical service
  APIs are pending.

## Iteration 14: Retrieval Transport Contracts

Status: implemented for transport-neutral DTOs; physical transport remains
pending.

- Add retrieval-owned command contracts for search, document delete, and raw
  document lookup.
- Add a retrieval-owned filter spec for search payload filters.
- Add a shared retrieval response envelope with structured error payloads.
- Add a transport-neutral retrieval API handler that dispatches payloads through
  the retrieval app context.
- Add an import-boundary guard for the retrieval API contract and handler
  modules.
- Add a retrieval API server context that future gRPC, HTTP, or queue transports
  can wrap.
- Extend the retrieval API import-boundary guard to cover the server context.
- Wire local manager retrieval composition through a project-planned retrieval
  API client backed by the server context.
- Add a local queue request/response transport for retrieval API calls on
  `retrieval.api.requests`.
- Add a retrieval API queue app context that starts/stops the queue consumer.
- Add manager retrieval client mode settings for direct local or queue-backed
  retrieval API execution.
- Extend retrieval API import-boundary coverage to the queue transport.
- Convert retrieval commands into existing retrieval facade request dataclasses.
- Keep the contracts free of manager/project internals and generated transport
  files.
- Serialize raw-document bytes as base64 metadata for future JSON, queue, or
  protobuf adapters.

## Iteration 15: Retrieval HTTP API Transport

Status: implemented for retrieval search, delete, raw lookup, and health.

- Add a minimal JSON HTTP adapter over the retrieval API server context.
- Expose `POST /search`, `POST /documents/delete`, `POST /documents/raw`, and
  `GET /health`.
- Return existing retrieval response envelopes with deterministic HTTP status
  mapping.
- Load physical retrieval HTTP settings from `configs/retrieval` and env
  examples.
- Keep the HTTP transport free of manager, project, ingestion, generated
  transport, and gRPC imports.

## Iteration 16: Manager Remote Retrieval HTTP Client

Status: implemented locally.

- Add manager retrieval mode `http` for executing retrieval calls through a
  separately running retrieval HTTP service.

## Iteration 17: Retrieval Placement Core And Local Execution

Status: implemented locally; production migration/reindex orchestration deferred.

- Add retrieval-owned placement models, routing keys, shard records, placement
  records, and placement plans.
- Add stable hashing and weighted rendezvous assignment for new routing keys.
- Add in-memory and SQLite placement registries.
- Add local placement config and register the configured Qdrant endpoint as the
  default local shard.
- Attach `placement_plan` to project search/ingest/delete plans.
- Preserve `placement_plan` through retrieval search/delete/index command
  contracts and split ingestion-to-index messages.
- Resolve placement targets to live Qdrant stores in retrieval indexing and
  retrieval HTTP/queue execution.
- Write indexed chunks to primary plus replica placement targets.
- Search bucketed read targets with primary-first replica failover and merge
  hits by score.
- Delete dense and sparse records from primary plus replica placement targets.
- Namespace search cache keys by placement version, shard ID, and routing key.
- Persist per-project/default routing policies in the placement registry.
- Keep versioned placement history and support explicit moving/stale/active
  rebalance state transitions.
- Add manager retrieval HTTP base URL and timeout settings under
  `configs/manager`.
- Add `RetrievalApiHttpClient` for `POST /search`, `POST /documents/delete`,
  and `POST /documents/raw` response-envelope calls.
- Keep project planning in the manager local composition while replacing only
  retrieval execution with the remote HTTP adapter.
- Preserve local and queue-backed retrieval modes.

## Iteration 17: Retrieval Index Worker Startup

Status: implemented locally.

- Add a standalone retrieval indexing worker entry point with
  `python -m retrieval_service.indexing.worker`.
- Load worker settings from `configs/retrieval` and retrieval-specific
  environment variables.
- Support local and SQLite queue adapters for `retrieval.index.requests`.
- Build retrieval-owned indexing dependencies without involving project
  service runtime composition.
- Start the retrieval indexing worker in local split-service mode and stop it
  through the local cleanup script.

## Iteration 18: Ingestion API Status And Control

Status: implemented locally.

- Add transport-neutral ingestion API contracts for job status payloads and
  response envelopes.
- Add an ingestion API handler over `IngestionAppContext` and the ingestion job
  repository.
- Add an ingestion API server context exposing `get_status(...)` and
  `health(...)` payload methods for future HTTP, gRPC, or queue transports.
- Keep the ingestion API free of manager, project, retrieval, generated
  transport, and gRPC imports.
- Leave queued ingest submission and compatibility execution unchanged.

## Iteration 19: Manager Ingestion API Status Client

Status: implemented locally.

- Add a manager-facing ingestion adapter that delegates ingest submission while
  serving status through the ingestion API server context.
- Map ingestion API status envelopes to shared `IngestJobResult` values.
- Preserve the existing pending fallback for missing job status.
- Use the ingestion API status adapter in embedded manager ingestion
  composition.
- Keep manager core and manager server bootstrap free of ingestion-service
  imports; temporary compatibility composition now lives in
  `local_runtime.manager_app`.

## Iteration 20: Ingestion Worker Retrieval Index Queue Wiring

Status: implemented locally.

- Add ingestion worker settings for retrieval index publication.
- Build a retrieval index queue automatically in the standalone ingestion
  worker when publication is enabled.
- Pass the configured retrieval index topic through to the ingestion consumer.
- Wire local split-service mode so ingestion publication and retrieval indexing
  consume the same SQLite queue database and topic.
- Keep publication disabled by default outside split-service/local opt-in modes.

## Iteration 21: Local Split Ingestion Index Smoke

Status: implemented locally.

- Add a lightweight SQLite queue smoke test for the local split ingestion to
  retrieval indexing handoff.
- Exercise ingestion request consumption, preparation metadata, retrieval index
  request publication, and retrieval index consumer processing through separate
  queue broker instances sharing one SQLite database.
- Use fakes for project-document ingest and indexing so the smoke test does not
  require Qdrant, embedding models, or network services.

## Iteration 22: Retrieval HTTP Server Startup

Status: implemented locally.

- Add a standalone retrieval HTTP server entry point with
  `python -m retrieval_service.server.worker`.
- Build retrieval-owned runtime dependencies for search, delete, raw lookup,
  caching, sparse retrieval, NER, object storage, and metrics.
- Serve the existing retrieval HTTP API transport over the retrieval API server
  context.
- Add optional local runner support with `--external-retrieval-http`, which
  starts the retrieval HTTP service and switches manager retrieval mode to HTTP.
- Keep the worker free of manager, project, ingestion, generated transport, and
  gRPC imports.

## Iteration 23: Local Runner Retrieval HTTP Mode Guard

Status: implemented locally.

- Keep `--external-retrieval-http` supported only with local manager project
  planning.
- Fail early when `--external-retrieval-http` is combined with
  `--external-project-service` or `--split-services`.
- Document the current project-planning constraint until project config/scope
  APIs are extracted.

## Iteration 24: Config Profile Variants

Status: implemented locally.

- Add explicit local and production Python profile defaults under `configs/`.
- Add a testing profile with in-memory defaults for tests.
- Move shared settings code to `configs/base.py` and keep `configs/config.py`
  as the stable active settings entrypoint.
- Make `configs/config_local.py` and `configs/config_production.py`
  active-compatible entrypoints so either profile can be promoted over
  `configs/config.py` without breaking imports.
- Support profile selection through `profile=...` and `RAG_CONFIG_PROFILE`.
- Preserve env override order: profile defaults, profile env file, component env
  files, then process environment variables.
- Keep local runner env defaults under `configs/local.env` /
  `configs/local.env.example` instead of `examples/local`.
- Document the optional deployment copy workflow for teams that promote a
  profile module into the active `config.py`.
- Reject unknown profile names and provide side-effect-free production
  validation for URLs, paths, modes, placement counts, and required secrets.

## Next Iteration: Independent Server Compliance

Status: pending.

- Make every independent server or node own an independent top-level workspace,
  runtime entrypoint, config folder, test folder, and deployment definition.
- Remove cross-service imports of internal modules, repositories, handlers,
  runtime objects, and implementation details.
- Remove shared parent classes, base service classes, inherited server
  frameworks, and cross-service runtime abstractions.
- Keep shared code limited to stable contracts, schemas, protocol clients,
  correlation IDs, common errors, and generic utilities that do not control
  server behavior.
- Add service import-boundary tests for manager, project, ingestion, retrieval,
  workflow log, broker, storage, and SQLite database node code.

## Next Iteration: Task Manager Dispatch Topology

Status: pending.

- Create the independent `task_manager_service` server workspace, entrypoint,
  config folder, and tests.
- Consume manager-published task intake messages from Redpanda.
- Create and update task lifecycle state, including accepted/running/completed
  and failed task states.
- Write Redis task status by `task_id`; apply TTL to completed task keys.
- Dispatch project/workflow/memory/other domain commands through Redpanda.
- Consume domain plan/info results and dispatch ingestion, retrieval, storage,
  indexing, or other helper commands through Redpanda.
- Consume helper results, aggregate final task results, update Redis, and
  publish final result events when needed.
- Keep retries, leases, attempt counts, backoff, and dead-letter behavior out of
  scope.

## Next Iteration: Redpanda Runtime Broker

Status: pending.

- Add a Redpanda/Kafka-compatible broker adapter for runtime service
  communication.
- Use Redpanda in local and production. Local means Redpanda runs on the same
  machine, not that services use in-memory, file, or SQLite queue shortcuts.
- Route manager task intake, task-manager domain commands, domain results,
  task-manager helper commands, helper results, and service events through
  Redpanda topics.
- Keep retries, leases, attempt counts, backoff, and dead-letter queues out of
  scope for this phase.
- Remove local runner paths that rely on in-memory, file-based, embedded, or
  SQLite queue communication for runtime service-to-service messaging.

## Next Iteration: Config And Test Separation

Status: pending.

- Move service-specific settings into service folders under `configs/`.
- Add missing config folders for broker and SQLite/database nodes.
- Reorganize tests into service folders under `tests/`.
- Move cross-service smoke tests to `tests/integration/`.
- Ensure integration tests exercise public APIs or Redpanda topics instead of
  importing service internals across folders.

## Later Iteration: Compatibility Composition Reduction

Status: pending.

- Move manager production composition away from project/RAG compatibility
  clients once physical service APIs exist.
- Replace remote compatibility gRPC with project-native task APIs for ingest,
  search, delete, and status.
- Remove legacy duplicate schemas and compatibility import shims.

## Guardrails

- Keep the external gRPC API stable until internal services are split.
- Add only narrow contracts to `shared`.
- Do not put Qdrant, parsers, project adapters, or business orchestration in
  shared code.
- Do not add shared parent service classes, inherited server frameworks, or
  cross-service runtime abstractions.
- Use Redpanda as the broker target for both local and production runtime.
- Keep local and production on the same code paths; only addresses,
  credentials, ports, and paths should differ by config.
