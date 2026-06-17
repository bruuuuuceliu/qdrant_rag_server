# Multi-Service Boundary Progress

**Reviewed**: 2026-06-16
**Design reference**: `docs/boundary.md`
**Current status**: partially extracted multi-service scaffold; not yet the ideal
multi-server architecture.

## Summary

### Manager Client Contracts

Status: accepted.

Implemented:

- manager-facing ingestion and retrieval client protocols
- compatibility adapters from `ProjectDocumentClient`
- `ManagerService` dispatch through service-specific clients
- split-client and compatibility-path tests

Verification:

- `pytest tests/test_manager_service.py -q`
- `pytest tests/test_ingestion_service_server.py tests/test_ingestion_worker_server.py -q`
- `pytest tests/test_shared_contracts.py -q`
- `pytest tests/test_manager_service.py tests/test_project_service_client.py tests/test_retrieval_service_facade.py -q`

### Ingestion Job Acceptance

Status: accepted.

Implemented:

- `QueuedIngestCommand` shared queue DTO and parser
- ingestion job creation before delegated compatibility execution
- worker wiring to `SQLiteIngestionJobRepository`
- response payload job ID preserved for repository-backed acceptance
- compatibility path when no repository is injected

Verification:

- `pytest tests/test_shared_contracts.py tests/test_ingestion_service_server.py tests/test_ingestion_jobs.py tests/test_ingestion_worker_server.py -q`
- `pytest tests/test_manager_service.py -q`

### Ingestion Preparation Metadata

Status: accepted.

Implemented:

- optional `IngestionService` preparation in the queued ingestion consumer
- durable job metadata updates for content hash, handler, chunk count, raw
  content length, content type, and chunker versions
- mapping-request support in `SourceDescriptor.from_request`
- standalone ingestion worker wiring for preparation before compatibility
  execution
- tests for preparation metadata and no-preparation compatibility

Verification:

- `pytest tests/test_ingestion_service_server.py tests/test_ingestion_worker_server.py -q`
- `pytest tests/test_ingestion_service.py tests/test_ingestion_service_server.py tests/test_ingestion_worker_server.py tests/test_ingestion_jobs.py tests/test_manager_service.py tests/test_shared_contracts.py -q`

### Retrieval Index Queue Worker

Status: accepted.

Implemented:

- `RetrievalIndexCommand` queue DTO for neutral retrieval indexing payloads
- `RetrievalIndexConsumer` that calls `IndexingService.index_chunks(...)`
- optional response topic publishing for success and failure
- tests for command parsing and worker behavior

Verification:

- `pytest tests/test_retrieval_index_consumer.py -q`

### Ingestion To Retrieval Index Publication

Status: accepted.

Implemented:

- optional retrieval indexing queue publication from the ingestion consumer
- retrieval index command payloads built from prepared ingestion chunks
- worker composition injection for a retrieval queue
- tests proving publication payloads parse through `RetrievalIndexCommand`
- no-queue compatibility behavior preserved

Verification:

- `pytest tests/test_ingestion_service_server.py tests/test_ingestion_worker_server.py tests/test_retrieval_index_consumer.py -q`
- `pytest tests/test_ingestion_service.py tests/test_ingestion_service_server.py tests/test_ingestion_worker_server.py tests/test_ingestion_jobs.py tests/test_retrieval_index_consumer.py tests/test_indexing_service.py tests/test_manager_service.py tests/test_shared_contracts.py -q`

### Retrieval Index App Context

Status: accepted.

Implemented:

- `RetrievalIndexAppContext` and `create_app(...)`
- enabled/disabled consumer lifecycle management
- focused app tests using the retrieval indexing queue consumer

Verification:

- `pytest tests/test_retrieval_index_consumer.py tests/test_retrieval_index_app.py -q`

### Retrieval Index Publication Validation

Status: accepted.

Implemented:

- validation of `collection_name` when retrieval publication is enabled
- structured validation failure responses for incomplete retrieval publication
- tests for success, validation failure, and compatibility-only ingestion

Verification:

- `pytest tests/test_ingestion_service_server.py tests/test_ingestion_worker_server.py tests/test_retrieval_index_consumer.py tests/test_retrieval_index_app.py -q`

### Retrieval Service App Context

Status: accepted.

Implemented:

- `RetrievalAppContext` and `create_app(...)`
- delegated search, delete, raw-document, and shutdown methods
- focused app tests alongside retrieval facade tests

Verification:

- `pytest tests/test_retrieval_service_app.py tests/test_retrieval_service_facade.py -q`

### Manager Local Retrieval Client

Status: accepted.

Implemented:

- `LocalRetrievalClient` manager-facing adapter
- public export from `manager_service`
- manager tests for split-client construction with independent retrieval
  delegation

Verification:

- `pytest tests/test_manager_service.py tests/test_retrieval_service_app.py -q`

### Manager Local Ingestion Client

Status: accepted.

Implemented:

- `LocalIngestionClient` manager-facing adapter
- repository-backed status conversion to shared `IngestJobResult`
- public export from `manager_service`
- manager tests for local ingestion and local retrieval client construction

Verification:

- `pytest tests/test_manager_service.py tests/test_ingestion_jobs.py -q`

### Manager Import Boundary Guard

Status: accepted.

Implemented:

- AST-based import-boundary test for manager core modules
- guard against direct manager core imports of project, retrieval, ingestion,
  Qdrant, and implementation internals

Verification:

- `pytest tests/test_manager_import_boundaries.py tests/test_manager_service.py -q`

### Manager Split-Client Composition

Status: accepted.

Implemented:

- manager app bootstrap now passes explicit ingestion and retrieval adapters to
  `ManagerService`
- composition root remains compatibility-based while the manager core uses
  split clients
- manager app tests assert the explicit adapters are present

Verification:

- `pytest tests/test_manager_service.py -q`

### Retrieval Index Command Validation

Status: accepted.

Implemented:

- retrieval-owned `collection_name` validation in `RetrievalIndexCommand`
- invalid command response coverage in the retrieval indexing consumer
- tests for valid parsing, parser rejection, and worker error response

Verification:

- `pytest tests/test_retrieval_index_consumer.py tests/test_retrieval_index_app.py tests/test_ingestion_service_server.py -q`

### Retrieval Index Import Boundary Guard

Status: accepted.

Implemented:

- AST-based import guard for retrieval indexing queue modules
- protection against direct imports from manager, project service, or ingestion
  service internals

Verification:

- `pytest tests/test_retrieval_index_import_boundaries.py tests/test_retrieval_index_consumer.py tests/test_retrieval_index_app.py -q`

### Ingestion Server Import Boundary Guard

Status: accepted.

Implemented:

- AST-based import guard for ingestion server queue modules
- protection against direct imports from manager, project, retrieval, and Qdrant
  internals in ingestion server app/consumer code

Verification:

- `pytest tests/test_ingestion_server_import_boundaries.py tests/test_ingestion_service_server.py -q`

### Roadmap Boundary Alignment

Status: accepted.

Implemented:

- updated implementation roadmap with retrieval app context and boundary guard
  iterations
- kept physical service APIs and production broker adapter marked pending

Verification:

- documentation-only change; covered by focused suite after surrounding sections

### Section Design Index

Status: accepted.

Implemented:

- added `docs/design/section-design-index.md` for accepted development-loop
  section docs
- linked the index from `docs/README.md`

Verification:

- documentation-only change; link target is repository-local

### Docs README Link Integrity

Status: accepted.

Implemented:

- removed stale missing-file links from `docs/README.md`
- added focused docs entry-point link test

Verification:

- `pytest tests/test_docs_links.py -q`

### Manager Context Ingestion Jobs

Status: accepted.

Implemented:

- `ManagerAppContext.ingestion_jobs` property
- manager app tests for embedded and external ingestion worker modes

Verification:

- `pytest tests/test_manager_service.py -q`

### Manager Local Retrieval Composition

Status: accepted.

Implemented:

- `ProjectPlannedRetrievalClient` that uses project gateway planning and
  retrieval-owned execution
- read-only `RagEngine.retrieval_service` property for local composition
- manager local mode now uses retrieval-facade execution for search/delete
- focused project client and manager app tests

Verification:

- `pytest tests/test_project_service_client.py tests/test_manager_service.py -q`

### Boundary Docs Refresh

Status: accepted.

Implemented:

- refreshed architecture, service-boundary, and contract text for local manager
  retrieval composition
- documented project-planned retrieval facade execution for local search/delete

Verification:

- covered by docs link and focused test runs after implementation

### Retrieval Index Command Validation

Status: accepted.

Implemented:

- retrieval-side validation for blank `collection_name` in index commands
- consumer error responses for invalid command payloads
- tests for parser validation and worker failure response behavior

Verification:

- `pytest tests/test_retrieval_index_consumer.py tests/test_retrieval_index_app.py -q`

### Manager Local Ingestion Composition

Status: accepted.

Implemented:

- `IngestionAppContext` now exposes its job repository
- embedded manager app mode initializes an ingestion job repository
- manager local embedded mode uses `LocalIngestionClient` for ingestion/status
  while preserving compatibility direct ingest execution

Verification:

- `pytest tests/test_manager_service.py tests/test_ingestion_service_server.py -q`

### Boundary Documentation Refresh

Status: accepted.

Implemented:

- roadmap updates for manager split clients, ingestion-to-index publication, and
  retrieval index queue worker
- architecture updates for current `retrieval.index.requests` behavior
- service-boundary updates for ingestion preparation/publication and retrieval
  index consumer ownership

Verification:

- `rg -n 'future `retrieval\\.index`|future retrieval\\.index|retrieval\\.index.*future|Next Iteration: Durable Production Broker' docs/architecture.md docs/service-boundaries.md docs/implementation-roadmap.md docs/contracts.md`

### Retrieval Transport Contracts

Status: accepted.

Implemented:

- `RetrievalSearchCommand`, `RetrievalDeleteDocumentCommand`, and
  `RetrievalRawDocumentCommand` for transport-neutral retrieval API payloads
- conversion from direct mappings or `{request_id, response_topic, request}`
  envelopes into existing retrieval facade request dataclasses
- `RetrievalResponseEnvelope` and `RetrievalApiError` for structured retrieval
  responses
- search-result and raw-document result mapping helpers, including base64
  serialization for raw document bytes
- focused tests for parsing, validation, conversion, and response mapping
- contract, architecture, roadmap, and section-design documentation updates

Verification:

- `pytest tests/test_retrieval_transport_contracts.py -q`

### Retrieval API Handler

Status: accepted.

Implemented:

- `RetrievalFilterSpec` for retrieval-owned transport filter payloads
- mapping-filter normalization during search command parsing
- `RetrievalApiHandler` for search, delete, and raw-document payload dispatch
  through a retrieval app context
- response-envelope mapping for success, validation errors, and unexpected app
  errors
- focused tests that avoid project-service filter classes at the transport
  boundary
- handler design, contracts, architecture, roadmap, and progress documentation
  updates

Verification:

- `pytest tests/test_retrieval_transport_contracts.py tests/test_retrieval_api_handler.py -q`

### Retrieval API Import Boundary Guard

Status: accepted.

Implemented:

- AST import-boundary guard for `retrieval_service.retrieval.contracts` and
  `retrieval_service.retrieval.handler`
- protection against imports from manager, project, ingestion, generated
  transport modules, and `grpc` in the transport-neutral retrieval API layer
- focused design and roadmap documentation updates

Verification:

- `pytest tests/test_retrieval_api_import_boundaries.py tests/test_retrieval_transport_contracts.py tests/test_retrieval_api_handler.py -q`

### Retrieval API Server Context

Status: accepted.

Implemented:

- `retrieval_service.server.create_app(...)` for retrieval-owned API server
  composition
- `RetrievalApiServerContext` exposing search, delete, and raw-document payload
  methods backed by `RetrievalApiHandler`
- shutdown delegation through `RetrievalAppContext`
- focused tests for payload dispatch and shutdown
- contracts, architecture, roadmap, section-index, and progress documentation
  updates

Verification:

- `pytest tests/test_retrieval_api_server.py tests/test_retrieval_api_handler.py tests/test_retrieval_transport_contracts.py -q`

### Retrieval Server Import Boundary Guard

Status: accepted.

Implemented:

- extended `tests/test_retrieval_api_import_boundaries.py` to guard
  `retrieval_service.server.app`
- protected the retrieval server context from manager, project, ingestion,
  generated transport, and `grpc` imports
- focused design, roadmap, section-index, and progress documentation updates

Verification:

- `pytest tests/test_retrieval_api_import_boundaries.py tests/test_retrieval_api_server.py -q`

### Manager Retrieval API Client

Status: accepted.

Implemented:

- `ProjectPlannedRetrievalApiClient` for manager-facing search/delete with
  project gateway planning and retrieval API server-context execution
- response-envelope mapping back to `SearchResult` and clear `RuntimeError`
  failures for unsuccessful retrieval API responses
- manager local composition now builds `retrieval_service.server` context and
  injects the API-backed retrieval client
- manager shutdown now closes the retrieval API context before the project app
- focused project-client and manager-app tests
- contracts, architecture, roadmap, section-index, and progress documentation
  updates

Verification:

- `pytest tests/test_project_service_client.py tests/test_manager_service.py -q`

### Retrieval API Queue Transport

Status: accepted.

Implemented:

- `RetrievalApiQueueConsumer` for `retrieval.api.requests`
- `RetrievalApiQueueClient` for request/response queue calls to retrieval API
  operations
- `RetrievalApiQueueTimeoutError` for missing responses
- support for search, delete, and raw-document operations using response
  envelopes from the retrieval API server context
- non-retryable `validation_error` envelopes for unknown operations
- focused LocalQueueBroker tests for success, validation, and timeout behavior
- contracts, architecture, roadmap, section-index, and progress documentation
  updates

Verification:

- `pytest tests/test_retrieval_api_queue.py tests/test_retrieval_api_server.py tests/test_retrieval_api_handler.py tests/test_retrieval_transport_contracts.py -q`

### Retrieval API Queue App Context

Status: accepted.

Implemented:

- `RetrievalApiQueueAppContext` for retrieval API queue worker composition
- `create_queue_app(...)` to build a retrieval API server context and optional
  `RetrievalApiQueueConsumer`
- enabled/disabled consumer startup modes
- shutdown sequencing for queue consumer and retrieval API context
- focused queue app tests using `LocalQueueBroker`
- roadmap, section-index, and progress documentation updates

Verification:

- `pytest tests/test_retrieval_api_queue_app.py tests/test_retrieval_api_queue.py tests/test_retrieval_api_server.py -q`

### Manager Retrieval Queue Mode

Status: accepted.

Implemented:

- manager retrieval settings for `MANAGER_RETRIEVAL_CLIENT_MODE`,
  `MANAGER_RETRIEVAL_TOPIC`, and `MANAGER_RETRIEVAL_RESPONSE_TIMEOUT`
- `get_float_value(...)` config helper for timeout parsing
- manager local mode support for direct retrieval API execution or queue-backed
  retrieval API execution
- embedded retrieval API queue app startup in manager queue mode
- queue-backed retrieval API client injection into `ProjectPlannedRetrievalApiClient`
- manager shutdown of the embedded retrieval queue app
- focused config and manager app tests for default, queue, and invalid modes
- env example, contracts, architecture, roadmap, section-index, and progress
  documentation updates

Verification:

- `pytest tests/test_app_config.py tests/test_manager_service.py tests/test_retrieval_api_queue_app.py tests/test_retrieval_api_queue.py -q`

### Retrieval API Queue Import Boundary Guard

Status: accepted.

Implemented:

- extended retrieval API import-boundary guard coverage to
  `retrieval_service.server.queue`
- protected retrieval API queue transport from manager, project, ingestion,
  generated transport, and `grpc` imports
- focused design, roadmap, section-index, and progress documentation updates

Verification:

- `pytest tests/test_retrieval_api_import_boundaries.py tests/test_retrieval_api_queue.py tests/test_retrieval_api_queue_app.py -q`

### Retrieval HTTP API Transport

Status: accepted.

Implemented:

- `RetrievalHttpApp` testable HTTP route dispatcher over the existing retrieval
  API server context
- physical stdlib asyncio HTTP server adapter for the retrieval API
- JSON routes for search, document delete, raw-document lookup, and health
- structured response-envelope handling for invalid JSON, validation failures,
  unknown routes, and unexpected retrieval failures
- retrieval HTTP settings in `configs/retrieval` and env examples
- import-boundary guard coverage for the retrieval HTTP transport
- focused HTTP transport tests

Verification:

- `pytest tests/test_retrieval_http_server.py tests/test_retrieval_api_import_boundaries.py tests/test_app_config.py -q`

The repository already has the right service-oriented shape for the target
design: `manager_service`, `project_service`, `ingestion_service`,
`retrieval_service`, `workflow_log_service`, `memory_service`, `shared`, and
service-specific config folders exist. The manager can route operations, ingest
can move through a queue, ingestion workers can run separately for local
multi-process development, retrieval has search/index/delete facades, and
workflow logs can consume lifecycle events.

The main gap is physical runtime ownership. The current system still relies
heavily on `project_service.rag.RagEngine` and a compatibility `RagService` gRPC
contract. The manager now expresses ingestion and retrieval ownership through
separate in-process client contracts, but those contracts still adapt the
compatibility project-document client until independent service APIs exist.
Ingestion queue workers still delegate to a project-document client, which then
runs the compatibility project/RAG path. The ideal architecture in
`docs/boundary.md` is therefore a good target, but the implementation is still in
a migration phase.

## Current Implementation Against Ideal Design

| Boundary area | Current implementation | Gap to ideal design |
| --- | --- | --- |
| Repository shape | Service folders and config namespaces exist for manager, project, ingestion, retrieval, workflow log, memory, shared, tests, docs, deployment, and examples. | Some folders are placeholders or compatibility layers. `memory_service` has no real service boundary yet. |
| Public manager | `manager_service` has route decisions, a gRPC server bootstrap, service-specific ingestion/retrieval client contracts, compatibility adapters, and a `ManagerService` facade. It routes ingest/search/delete/status for `project_document`. | Manager still adapts the compatibility `ProjectDocumentClient` at composition roots because independent ingestion/retrieval network APIs do not exist yet. |
| Routing registry | `shared.contracts.data_types` defines `project_document`, `agent_memory`, and `workflow_log`; manager uses this registry. | Registry is route-label only. Data-type-specific schemas, policies, parsing, and retrieval defaults are still not modeled. |
| Project service | `project_service` owns project adapters, config repository, gateway planning, scope construction, and gRPC compatibility app. | It still composes the local RAG engine and much of the end-to-end workflow. It should become config/scope/policy only. |
| Ingestion service | `ingestion_service.service.IngestionService` can load, route, parse, clean, and chunk one source. Handlers, source fetchers, normalization, chunking, jobs, and storage folders exist. | Queue consumer does not yet call this service as the primary runtime path. It delegates to `ProjectDocumentClient.ingest`, which runs compatibility orchestration. |
| Task services | No separate task-service package exists. Batch/crawl/fan-out is represented only as an ideal design concept. | Need explicit task worker boundary and topics for batch expansion, website crawling, fan-out, retry, and fan-in. |
| Ingestion queue | `shared.queue` provides `QueueMessage`, `QueueBroker`, in-process local broker, and SQLite broker. Manager can publish to `ingestion.requests`; ingestion worker consumes it and responds on a per-request topic. | SQLite broker is local-development only. No production broker adapter, claim timeout, retry policy, dead-letter topic, or idempotent retry envelope. |
| Ingestion job state | `ingestion_service.jobs` has memory and SQLite repositories. App config includes ingestion job DB settings. | Job state is partly driven by `RagEngine`; ingestion workers are not yet the sole owners of job execution state. |
| Retrieval service | `retrieval_service.retrieval.RetrievalService` owns search/delete/raw reads. `retrieval_service.indexing.IndexingService` owns dense/sparse embedding, entity enrichment, and Qdrant upsert. | There is no independent retrieval server API for manager-facing search/delete/index commands. Facades are used through compatibility composition. |
| Indexing queue | Ideal topic `retrieval.index.requests` is documented. Indexing facade exists. | No queue consumer or worker service currently consumes indexing requests. Ingestion does not yet publish prepared chunks to a retrieval indexing queue. |
| Workflow log service | `workflow_log_service` has a consumer, server app, SQLite repository, models, config, and tests. It consumes `ingestion.events`. | It is wired locally through an in-process event broker in `project_service.server.app`; production broker, retry, and cross-process deployment remain pending. |
| Memory service | `memory_service` package exists. `agent_memory` route is reserved. | No schemas, storage, server, retrieval behavior, or lifecycle policy implemented. |
| Storage boundaries | Project config, ingestion jobs, workflow logs, retrieval cache, Qdrant, object storage, and version manager exist as separate abstractions. | Some state ownership is still blurred by `RagEngine`. Services can still reach implementation objects directly inside local composition. |
| Synchronous APIs | gRPC compatibility service supports search, ingest, ingest status, generation, and health. Remote project/RAG client exists for search, ingest, and status. | Proto lacks explicit delete, data type, and first-class raw-content fields. Manager-native service contracts are not complete. |
| Async events | Ingest lifecycle events publish to `ingestion.events` best-effort. Workflow log can persist them. | Retrieval index events, cache events, retry events, and dead-letter events are not implemented. |
| Observability | Health checker and metrics scaffold exist. Queue messages carry correlation IDs in some paths. | Correlation IDs are not enforced across every public request, service call, queue message, and event. Metrics are not yet a full service-level observability layer. |
| Tests | Tests cover routing, manager service, project client, ingestion service, ingestion server, worker server, SQLite queue, workflow log service, retrieval/indexing facades, and RAG behavior. | More cross-process, broker, live Qdrant, idempotency, retry, and failure-isolation tests are needed. |

## Implemented And Reliable Enough To Keep

- Folder-level service split is directionally correct.
- `ManagerRouter` correctly expresses the desired owner for
  `project_document` ingest/search/delete/status.
- `ProjectDocumentClient` is a useful compatibility boundary during migration.
- `LocalQueueBroker` and `SQLiteQueueBroker` preserve topic/key/headers/payload
  semantics and are good local substitutes for a future broker.
- Ingestion parsing, source loading, normalization, chunking, and file routing
  exist in `ingestion_service` and should become the primary ingestion runtime.
- Retrieval search/delete/raw and indexing facades exist and should become the
  manager-facing retrieval server internals.
- Workflow log service already has independent consumer/repository/server code.
- Existing docs now clearly separate current service boundaries, contracts,
  roadmap, and the ideal system boundary.

## Important Mismatches With `docs/boundary.md`

1. **Manager target services are logical, not physical yet.**

   The router says ingest belongs to ingestion and search/delete belong to
   retrieval, but `ManagerService` calls the same project-document client for
   all operations. This is acceptable for migration but not the final boundary.

2. **Ingestion workers do not own ingestion execution end to end.**

   The queue consumer accepts `ingestion.requests`, then calls
   `project_documents.ingest(...)`. The target design expects ingestion workers
   to fetch, parse, normalize, chunk, persist job state, and publish indexing
   commands directly.

3. **Indexing is a facade, not an async service.**

   `IndexingService` is well-shaped, but there is no `retrieval.index.requests`
   worker that consumes prepared chunks from ingestion.

4. **The project service is still too central.**

   It currently wires the engine, Qdrant store, embeddings, sparse encoder,
   object storage, workflow events, cache, generation, health, and versioning in
   one local composition root. The ideal design makes project service own only
   project config, scope, adapters, and policy.

5. **Queue semantics are not production-grade.**

   SQLite queue supports local multi-process testing but not durable production
   semantics such as visibility timeout, retry count, dead-letter topics,
   partitioning, consumer groups, or broker metrics.

6. **Transport contracts are still compatibility contracts.**

   The active gRPC API is `RagService`. It does not yet model the manager,
   ingestion, retrieval, project, workflow log, and memory contracts as separate
   service APIs.

7. **Task services are missing.**

   The ideal design calls for task services to split batch, website crawl, and
   large-source work before ingestion workers. No implementation exists yet.

8. **Memory service is reserved only.**

   It is correctly kept out of the current critical path, but it is not a real
   service yet.

## Development Plan To Complete The Design

### Phase 1: Stabilize Current Migration Baseline

Goal: make the current compatibility architecture explicit and safe before
extracting more services.

- Keep `docs/boundary.md`, `docs/service-boundaries.md`, `docs/contracts.md`,
  and this file aligned after each boundary-changing implementation.
- Add a small architecture test or import-boundary check that prevents
  `manager_service` from importing parser, Qdrant, embedding, or engine internals.
- Add explicit TODO markers or issues for every compatibility call where
  manager or ingestion still uses `ProjectDocumentClient` instead of a final
  service-specific client.
- Verify the current test suite after this documentation update.

Exit criteria:

- Existing tests pass.
- Compatibility dependencies are documented and intentionally contained.
- No new code depends directly on `project_service.rag.RagEngine` outside
  compatibility composition roots.

### Phase 2: Add Service-Specific Client Contracts

Goal: replace the single project-document compatibility client at the manager
boundary with owner-specific contracts.

- Add manager-facing `ProjectConfigClient`, `IngestionClient`,
  `RetrievalClient`, and `WorkflowLogClient` protocols.
- Keep adapters that wrap the existing `ProjectDocumentClient` temporarily so
  behavior does not change during extraction.
- Update `ManagerService` so route targets call the matching client type:
  project for scope/config, ingestion for ingest/status, retrieval for
  search/delete, workflow log for audit reads.
- Add tests that prove manager routing no longer needs one combined
  project-document client.

Exit criteria:

- Manager code expresses the same boundaries as `ManagerRouter`.
- Compatibility wrappers are isolated and easy to delete later.

### Phase 3: Make Ingestion Service Own Ingest Execution

Goal: move runtime ingestion work from compatibility project/RAG orchestration
into `ingestion_service`.

- Define a typed ingestion command DTO for `ingestion.requests` payloads.
- Update `IngestionRequestConsumer` to create durable job records directly.
- Use `IngestionService.process(...)` as the primary source fetch, route,
  parse, normalize, and chunk path.
- Store raw artifacts through ingestion-owned storage when policy requires it.
- Publish lifecycle events from ingestion-owned code.
- Keep a compatibility adapter only for behavior not yet migrated.
- Add idempotency using job ID, document ID, project/user/KB, and content hash.

Exit criteria:

- Ingest status is owned by `ingestion_service.jobs`.
- Queue consumer no longer delegates normal document ingestion to
  `ProjectDocumentClient.ingest`.
- Ingestion can produce neutral prepared chunks without importing retrieval
  internals.

### Phase 4: Add Retrieval Indexing Queue Workers

Goal: make indexing an async retrieval-service responsibility.

- Define `retrieval.index.requests` message schema for prepared chunks,
  retrieval payloads, collection name, retrieval settings, and job ID.
- Add a retrieval indexing worker/server that consumes indexing requests and
  calls `IndexingService.index_chunks(...)`.
- Publish `retrieval.index.events` for running, completed, and failed states.
- Decide how indexing completion updates ingestion job status: direct ingestion
  callback, status event, or shared job-result topic.
- Add retry and idempotency behavior for duplicate indexing messages.

Exit criteria:

- Ingestion publishes prepared chunks to retrieval indexing queue.
- Retrieval indexing workers own embedding, sparse encoding, entity enrichment,
  and Qdrant upsert.
- Successful indexing can complete the ingest job without project engine
  orchestration.

### Phase 5: Expose Independent Retrieval APIs

Goal: make retrieval search and delete physically owned by retrieval service.

- Add retrieval-service server entry point for search, delete, raw lookup,
  health, and index status.
- Add a manager-facing `RemoteRetrievalClient` and local adapter.
- Move search/delete manager dispatch away from the project/RAG compatibility
  service.
- Extend transport DTOs with explicit `data_type`, `kb_id`, filters, retrieval
  mode, and delete policy fields.
- Add live Qdrant integration tests for dense, sparse, hybrid, delete, and cache
  invalidation where infrastructure is available.

Exit criteria:

- Manager search/delete calls `retrieval_service`, not `project_service`.
- Retrieval service can run as its own process in local split-service mode.

### Phase 6: Narrow Project Service To Config And Scope

Goal: remove project service from heavy RAG execution.

- Keep project adapters, project config repository, scope rules, project policy,
  and visibility decisions in `project_service`.
- Move or delete compatibility engine wiring from the normal project-service
  path once ingestion and retrieval services own their work.
- Add typed adapter-specific config APIs instead of relying only on generic JSON
  config maps.
- Make project service provide only config/scope/policy responses to manager,
  ingestion, and retrieval.

Exit criteria:

- `project_service` no longer owns Qdrant, embeddings, chunk indexing,
  retrieval ranking, or generation wiring in the normal runtime path.

### Phase 7: Add Task Services

Goal: implement the async fan-out/fan-in layer described in the ideal design.

- Add a task-service package or service folder for batch, crawl, and large-file
  orchestration.
- Define `ingestion.tasks` message contracts.
- Implement batch document expansion and website crawl expansion as first
  concrete task types.
- Add bounded retry, subtask tracking, and final task status aggregation.

Exit criteria:

- Manager can submit a batch or crawl request without knowing the subtask
  execution details.
- Ingestion workers consume source-specific tasks rather than manager-shaped
  batch requests.

### Phase 8: Add Production Broker Semantics

Goal: replace local-only queue behavior with production-ready async handling.

- Choose and implement a broker adapter behind `shared.queue.QueueBroker`
  such as Redis Streams, NATS, Kafka, or Redpanda.
- Add delivery metadata: attempt count, first-seen timestamp, last error,
  visibility timeout or claim lease, and idempotency key.
- Add retry topics and `dead_letter` topic handling.
- Add broker metrics: depth, age, attempts, processing latency, failures, and
  dead-letter counts.
- Keep `LocalQueueBroker` and `SQLiteQueueBroker` for tests and local
  development only.

Exit criteria:

- Async ingestion/indexing can survive process restarts and worker failure.
- Failed messages are retryable and eventually dead-lettered with enough
  context for repair.

### Phase 9: Complete Workflow And Observability

Goal: make lifecycle tracing first-class across the service graph.

- Enforce correlation IDs on every public request, service call, queue message,
  and lifecycle event.
- Add retrieval index events and cache events to workflow logging.
- Add status/audit query API to workflow log service.
- Add structured logs and service metrics for manager, ingestion, retrieval,
  task workers, workflow log, and broker adapters.
- Add health checks for each independent service and its owned dependencies.

Exit criteria:

- A document can be traced from manager acceptance through ingestion, indexing,
  retrieval readiness, and workflow log persistence.

### Phase 10: Add Reserved Services And Data-Type Expansion

Goal: safely grow beyond project documents after the core path is stable.

- Implement `memory_service` only after project-document ingest/search/delete is
  independently owned and tested.
- Define data-type-specific schemas, parsing rules, retrieval defaults, storage
  policies, and deletion semantics.
- Expand manager routing to executable `agent_memory` and workflow-log read
  routes when the owning services are ready.

Exit criteria:

- New data types can be added without changing parser, retrieval, and storage
  behavior for project documents.

## Recommended Next Milestone

```text
Manager-owned routing with separate client contracts, ingestion-owned job
execution, and retrieval-owned async indexing.
```

This is the smallest milestone that turns the current scaffold into the actual
architecture described in `docs/boundary.md` without prematurely adding memory,
advanced auth, or a full production broker.

## Verification Needed Next

- Run the full Python test suite.
- Add focused tests for manager route-to-client ownership after client contracts
  are split.
- Add ingestion queue tests that verify durable job creation happens before
  async processing.
- Add indexing queue worker tests for success, retryable failure, duplicate
  message handling, and lifecycle events.
- Add optional live Qdrant tests for dense, sparse, hybrid, delete, and cache
  invalidation.
- Add cross-process local split-service smoke test using manager, project,
  ingestion worker, workflow log, SQLite queue, and Qdrant.

## Documentation Policy

Status documents should distinguish:

- implemented scaffold
- local compatibility behavior
- physically independent service behavior
- mocked unit coverage
- live integration coverage
- production-ready behavior

Avoid percentage-complete claims. The useful question is whether each boundary
is owned by the correct service, accessed through the correct contract, and
verified under the failure modes expected by the ideal architecture.
