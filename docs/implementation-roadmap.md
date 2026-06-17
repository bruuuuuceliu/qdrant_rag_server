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
consumption; retry/dead-letter behavior remains a future broker-adapter
concern.

- Publish ingest/index lifecycle events through `shared.queue`.
- Wire the local app with a bounded `LocalQueueBroker` for `ingestion.events`.
- Keep event publishing best-effort so lifecycle logging does not block ingest.
- Define retry/dead-letter behavior before adding a network broker.
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
- Keep clients in-process for now while preserving a replacement point for
  future gRPC or queue-backed clients.
- Add tests for manager routing through the client boundary.

## Iteration 7: Ingestion Request Queue Consumer

Status: implemented locally with multi-process local worker support.

- Add `ingestion_service.server` with an `ingestion.requests` queue consumer.
- Wire the local manager app to publish ingest requests through the queue and
  wait for a per-request response topic.
- Add standalone ingestion worker server mode backed by a local SQLite queue for
  multi-process development while keeping the broker contract replaceable.
- Add typed ingestion service settings under `configs/ingestion`.
- Keep the consumer local and in-process for now while preserving the
  Kafka-compatible message shape in `shared.queue`.

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
- Add ingestion worker configuration for `INGESTION_PROJECT_CLIENT_MODE=local|grpc`
  and `INGESTION_PROJECT_GRPC_TARGET`.
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

## Next Iteration: Physical Ingestion Service APIs And Retrieval Worker Startup

Status: pending.

- Add manager-facing remote retrieval HTTP client composition when manager and
  retrieval run in separate processes.
- Add transport startup for the retrieval indexing worker.
- Add independent ingestion-service transport for job status and worker control.
- Move manager production composition away from project/RAG compatibility
  clients once physical service APIs exist.

## Later Iteration: Durable Production Broker Adapter

Status: pending.

- Add a real broker adapter such as Redis Streams, NATS, or Kafka behind
  `shared.queue.QueueBroker`.
- Add claim timeout/retry/dead-letter semantics for failed ingestion workers.
- Keep SQLite queue as a local-development adapter only.

## Guardrails

- Keep the external gRPC API stable until internal services are split.
- Add only narrow contracts to `shared`.
- Do not put Qdrant, parsers, project adapters, or business orchestration in
  shared code.
- Prefer local, testable abstractions before adding Kafka/Redpanda or extra
  infrastructure.
