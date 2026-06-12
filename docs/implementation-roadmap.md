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

Status: implemented locally.

- Add `ingestion_service.server` with an `ingestion.requests` queue consumer.
- Wire the local manager app to publish ingest requests through the queue and
  wait for a per-request response topic.
- Add typed ingestion service settings under `configs/ingestion`.
- Keep the consumer local and in-process for now while preserving the
  Kafka-compatible message shape in `shared.queue`.

## Guardrails

- Keep the external gRPC API stable until internal services are split.
- Add only narrow contracts to `shared`.
- Do not put Qdrant, parsers, project adapters, or business orchestration in
  shared code.
- Prefer local, testable abstractions before adding Kafka/Redpanda or extra
  infrastructure.
