# qdrant_rag_server Development Handoff

Date paused: 2026-06-12

## Resume Prompt

Continue the job in `./task.md`.

You are working in `/home/bruce/workplace/qdrant_rag_server`. Continue developing this project into a functional, well-structured multi-service RAG platform. Keep service boundaries clear, preserve user changes, run tests after each meaningful version, update docs only where useful, and do not mark the overall goal complete until the project is genuinely in good shape.

## Original Goal

The project should evolve from a monolithic RAG server into a simple but well-separated multi-service architecture:

- A manager service receives incoming requests and routes them to the correct service.
- Project document retrieval, ingestion, qdrant/indexing operations, workflow logs, and future agent memory functionality are separated by folders and service boundaries.
- Heavy tasks such as document ingestion workers should run as independent service groups.
- Services should communicate through explicit service clients and async queue-style contracts, not direct internal code calls across ownership boundaries.
- Shared code is allowed under a common parent where it is truly reusable.
- Configs and env examples belong under `./configs/`.
- Necessary architecture/contracts/progress docs belong under `./docs/`, without over-documenting.
- The structure should stay efficient, essential, and avoid unnecessary complexity.

## Current Status

The repo is intentionally dirty with many modifications and new files from the ongoing refactor. Do not revert unrelated changes. Treat the current worktree as the source of truth.

High-level service folders now exist:

- `manager_service/`
- `project_service/`
- `ingestion_service/`
- `retrieval_service/`
- `workflow_log_service/`
- `memory_service/` reserved for future work
- `shared/`

Config/doc folders added or expanded:

- `configs/manager/`
- `configs/ingestion/`
- `configs/memory/`
- `configs/workflow_log/`
- `docs/architecture.md`
- `docs/service-boundaries.md`
- `docs/contracts.md`
- `docs/implementation-roadmap.md`

Latest verification after the resumed manager-boundary work is green:

```bash
python -m pytest -q
# 223 passed in 5.20s
```

Focused manager verification after the same work is also green:

```bash
python -m pytest tests/test_manager_service.py -q
# 23 passed in 1.42s
```

## Completed Work So Far

### Ingestion Examples And Local Files

Earlier work added or updated ingestion showcases in `examples/unites/ingestion.py`.

The ingestion flow was updated to accept local file paths as inputs, using sample files from:

- `examples/unites/example_files/`

### Ingestion Chunking And Cleaning

The ingestion/chunking behavior was investigated after a PDF book was assigned to one chunk while DOCX got page-level chunks.

Design direction implemented earlier:

- Prefer structural/page-aware extraction where available.
- Preserve metadata including `start_page` and `end_page`.
- Avoid creating one huge PDF chunk.
- Improve cleaning to remove document rubbish where reasonable.
- Keep raw page provenance so downstream retrieval can cite source ranges.

Relevant areas:

- `retrieval_service/ingest/pipeline.py`
- `retrieval_service/ingest/workers.py`
- related ingestion tests

### Durable Ingestion Jobs

Ingestion jobs are now backed by a SQLite repository:

- `ingestion_service/jobs/repository.py`
- `ingestion_service/jobs/sqlite.py`
- `ingestion_service/schemas/jobs.py`
- `tests/test_ingestion_jobs.py`

The RAG engine now uses durable job status storage instead of only volatile memory.

### Queue Abstractions

Queue contracts and a local in-process broker were added:

- `shared/queue/protocols.py`
- `shared/queue/local.py`
- `shared/queue/__init__.py`

The local broker is used for tests and local composition, with Kafka-like message semantics.

### Manager Service

Manager routing and facade were added:

- `manager_service/routing/router.py`
- `manager_service/service.py`
- `manager_service/clients.py`
- `manager_service/errors.py`
- `manager_service/server/app.py`
- `tests/test_manager_service.py`

The manager routes:

- project document ingestion to ingestion service/request queue
- project document search to retrieval/project document client
- project document status to project document client
- future agent memory routes as reserved
- future workflow log routes as reserved/async

Latest manager-boundary tightening:

- Dict-style requests now read `metadata.data_type` before routing, so reserved future routes such as `agent_memory` cannot slip through as default project-document ingests.
- Queued ingestion failures now raise `ManagerIngestFailedError` instead of bare `RuntimeError`.
- Queued ingestion response timeouts now raise `ManagerIngestTimeoutError`.
- These errors are exported from `manager_service/__init__.py`.

### Ingestion Request Consumer

An ingestion service app and consumer were added:

- `ingestion_service/server/app.py`
- `ingestion_service/server/consumer.py`
- `configs/ingestion/config.py`
- `tests/test_ingestion_service_server.py`

Current local request/response contract:

- manager publishes to `ingestion.requests`
- ingestion consumer calls project document ingest client
- ingestion consumer publishes response to `ingestion.requests.responses.<request_id>`
- manager waits for response and returns `IngestResult`

### Project Service Client Boundary

A local project service client facade was added:

- `project_service/client.py`
- `tests/test_project_service_client.py`

This provides a manager-facing client contract over project document operations.

### Retrieval And Indexing Facades

Retrieval/indexing service facades were added:

- `retrieval_service/retrieval/service.py`
- `retrieval_service/indexing/service.py`
- `tests/test_retrieval_service_facade.py`
- `tests/test_indexing_service.py`

### Workflow Log Service

A durable workflow log service was added:

- `workflow_log_service/models.py`
- `workflow_log_service/repository.py`
- `workflow_log_service/consumer.py`
- `workflow_log_service/server/app.py`
- `configs/workflow_log/config.py`
- `tests/test_workflow_log_service.py`

Project app composition now creates a workflow log app and event queue when configured.

### Project App Composition

`project_service/server/app.py` now returns an `AppContext` that includes:

- `project_client`
- `ingest_event_broker`
- `workflow_log_app`
- `health_checker`
- `_NoopServer` when `start_server=False`

`create_app(settings=None, *, start_server=True)` can now build the project service internals without binding its public gRPC server. This is used by the manager app so public traffic can route through the manager.

### Manager-Owned gRPC Boundary

This was the last active work before pausing.

New files/changes:

- `manager_service/server/grpc/__init__.py`
- `manager_service/server/grpc/server.py`
- `manager_service/server/app.py`
- `project_service/server/app.py`
- `tests/test_manager_service.py`

`manager_service.server.app.create_app()` now:

1. Creates the project app with `start_server=False`.
2. Creates a local request broker.
3. Creates the ingestion app/consumer.
4. Creates `ManagerService`.
5. Starts the manager-owned gRPC compatibility server on `project_app.settings.grpc_port`.
6. Exposes `context.server` as the manager gRPC server.

`ManagerRagServiceServicer` currently routes:

- `Search` through `ManagerService.search`
- `Ingest` through `ManagerService.ingest`
- `GetIngestJobStatus` through `ManagerService.ingest_status`
- `Generate` through the project generation engine for compatibility
- `HealthCheck` through the project health checker for compatibility

Latest gRPC patch tightened error mapping:

- `QueueFullError` maps to `RESOURCE_EXHAUSTED`.
- `TimeoutError` maps to `DEADLINE_EXCEEDED`.
- `ManagerIngestFailedError` maps to `INTERNAL` with the service failure message.
- generic unexpected ingest errors map to `INTERNAL`.
- ingest status now maps manager `ValueError` to `INVALID_ARGUMENT` and unexpected failures to `INTERNAL`.

Focused tests added in `tests/test_manager_service.py`:

- manager app creates project app with `start_server=False`
- manager app starts `serve_manager_grpc`
- manager app shutdown stops manager server
- manager gRPC `Search` routes through manager
- manager gRPC `Ingest` routes through manager
- queue-full ingest maps to `RESOURCE_EXHAUSTED`
- manager gRPC `GetIngestJobStatus` routes through manager
- dict request metadata is honored for reserved-route rejection
- failed queued ingest responses raise `ManagerIngestFailedError`

Focused verification after this patch:

```bash
python -m pytest tests/test_manager_service.py -q
# 23 passed
```

Full-suite verification after this patch:

```bash
python -m pytest -q
# 223 passed
```

## Important Current Files

Core composition and boundaries:

- `manager_service/errors.py`
- `manager_service/server/app.py`
- `manager_service/server/grpc/server.py`
- `manager_service/service.py`
- `manager_service/routing/router.py`
- `project_service/server/app.py`
- `project_service/client.py`
- `ingestion_service/server/app.py`
- `ingestion_service/server/consumer.py`
- `workflow_log_service/server/app.py`
- `shared/queue/`

Docs:

- `docs/architecture.md`
- `docs/service-boundaries.md`
- `docs/contracts.md`
- `docs/implementation-roadmap.md`

Tests to keep close:

- `tests/test_manager_service.py`
- `tests/test_ingestion_service_server.py`
- `tests/test_project_service_app.py`
- `tests/test_project_service_client.py`
- `tests/test_workflow_log_service.py`
- `tests/test_phase11_e2e.py`

## Next Steps

Verification is current and green, but rerun at least the focused manager suite before the next code change if the worktree changes:

```bash
python -m pytest tests/test_manager_service.py -q
python -m pytest -q
```

Suggested next iteration:

1. Define a shared transport DTO/error envelope for queued ingest responses under `shared/` or `shared/contracts`.
2. Use that envelope in `ingestion_service/server/consumer.py` and `manager_service/service.py` instead of opaque dict/string errors.
3. Map stable error codes to gRPC status codes in `manager_service/server/grpc/server.py`.
4. Confirm workflow log events are emitted from ingestion and stored durably in the expected schema.
5. Review `manager_service/server/grpc/server.py` for any compatibility gaps with `project_service/server/grpc/server.py`.
6. Decide whether manager `Generate` should remain compatibility-only or move behind a proper manager route.
7. Continue splitting service-owned concerns only where the boundary is clear; avoid large abstract rewrites.

Sub-agent review result from 2026-06-12:

- Highest-value next local improvement is a typed queued-ingest response envelope.
- Current issue: `ingestion_service/server/consumer.py` still publishes `ok=False` with `error=str(exc)`, and the manager now maps that to `ManagerIngestFailedError` but still receives an untyped payload.
- Desired envelope fields: `request_id`, `ok`, `result`, `error.code`, `error.message`, and optionally `error.retryable`.
- This should tighten the manager/ingestion boundary without a broad refactor and prepare the local queue contract for Kafka or another broker adapter.

## Known Risks / Open Design Questions

- Manager-owned gRPC currently reuses the existing project proto for compatibility. This is practical, but the public API is still named `RagService`, not `ManagerService`.
- `Generate` is delegated directly to the project generation engine. This preserves behavior but is not yet a pure manager-routed service boundary.
- `ManagerService._queue_ingest` still waits synchronously for a queue response. That is useful for API compatibility, but future production design may need immediate job acceptance plus async status polling.
- Queued ingest response payloads are still untyped dicts even though manager-side errors are now typed.
- The local queue is only an in-process stand-in. A real deployment needs Kafka or another broker adapter behind the same queue contracts.
- The worktree contains many uncommitted files. Do not revert them unless explicitly asked.
- Sub-agent spawning works if completed agents are closed first; one explorer was used for the typed envelope recommendation.

## Bug Log

Fixed during the latest resumed session:

1. Manager app test fake did not match the new manager-owned gRPC bootstrap.
   - Symptom: `tests/test_manager_service.py` failed because `_FakeProjectApp` had no `health_checker`.
   - Fix: added fake health checker/server support and patched `serve_manager_grpc` in the test so the test verifies composition without binding a real gRPC port.
   - Verification: `python -m pytest tests/test_manager_service.py -q` passes.

2. Manager bootstrap could accidentally start the old project gRPC server and bypass manager routing.
   - Symptom/risk: public gRPC traffic could still enter the project service directly instead of `ManagerService`.
   - Fix: `project_service.server.app.create_app(..., start_server=False)` now supports internal-only composition, and `manager_service.server.app` starts the manager-owned gRPC server.
   - Verification: manager app tests assert `create_project_app(..., start_server=False)` and manager server ownership.

3. Manager gRPC ingest mapped too many runtime failures as queue saturation.
   - Symptom/risk: generic `RuntimeError` could become `RESOURCE_EXHAUSTED`, hiding internal failures as overload.
   - Fix: queue-full uses `QueueFullError`; timeout uses `TimeoutError`/`ManagerIngestTimeoutError`; failed downstream ingest uses `ManagerIngestFailedError`; unexpected errors remain `INTERNAL`.
   - Verification: tests cover queue-full mapping and failed queued ingest behavior.

4. Dict-style manager ingest requests ignored `metadata.data_type`.
   - Symptom/risk: `{"metadata": {"data_type": "agent_memory"}}` could be routed as default `project_document`, bypassing reserved-route rejection.
   - Fix: `ManagerService` now reads fields and metadata from both mapping requests and DTO/object requests.
   - Verification: `test_rejects_reserved_future_route_from_mapping_metadata`.

5. Queued ingest failure was represented as a bare `RuntimeError`.
   - Symptom/risk: manager/transport layers had no domain-specific error type for failed ingestion-service responses.
   - Fix: added `manager_service/errors.py` with `ManagerIngestFailedError` and `ManagerIngestTimeoutError`, exported them, and wired them into manager service/gRPC handling.
   - Verification: `test_ingest_queue_failure_raises_manager_error`.

Known remaining bugs/design defects:

1. Queued ingest response payloads are still untyped dicts.
   - Current behavior: `ingestion_service/server/consumer.py` publishes `ok`, `error`, and `result` as ad hoc fields.
   - Risk: manager still interprets opaque payloads and cannot reliably distinguish validation, unsupported content, parsing, downstream, retryable, and internal failures.
   - Next fix: introduce a shared ingest queue response envelope with `request_id`, `ok`, `result`, `error.code`, `error.message`, and optional `error.retryable`.

2. Manager still imports project/retrieval DTOs when decoding successful ingest queue responses.
   - Current behavior: `_ingest_result_from_payload` imports `project_service.schemas.IngestResult` and `retrieval_service.core.schemas.JobStatus`.
   - Risk: this blurs the intended service boundary.
   - Next fix: move transport-neutral result/envelope DTOs into `shared/` or `shared/contracts`.

3. Manager-owned gRPC is compatibility-shaped, not a clean manager API.
   - Current behavior: it reuses `RagService` proto and delegates `Generate` directly to the project generation engine.
   - Risk: manager boundary is improved but not fully clean.
   - Next fix: either document compatibility explicitly as temporary or introduce manager-native transport contracts.

4. Queue implementation is local-only.
   - Current behavior: `LocalQueueBroker` is in-process and adequate for tests/local composition.
   - Risk: does not prove cross-server communication behavior.
   - Next fix: add a broker adapter interface implementation for Kafka/NATS/Redis only after the local typed contract is stable.

5. Synchronous request/response ingest queue semantics may not match production needs.
   - Current behavior: manager waits for an ingestion service response before returning.
   - Risk: this preserves current API compatibility but may not scale for long-running ingestion.
   - Next fix: consider immediate job acceptance plus status polling once transport contracts are typed.

## Current Git Status Summary

At pause time, `git status --short` showed many modified and untracked files. This is expected.

Modified tracked files include:

- `configs/config.py`
- env examples under `configs/`
- multiple `project_service/`, `retrieval_service/`, `ingestion_service/` files
- `project_service/server/app.py`
- `project_service/server/grpc/server.py`
- several tests
- `pyproject.toml`

Untracked important additions include:

- `configs/ingestion/`
- `configs/manager/`
- `configs/memory/`
- `configs/workflow_log/`
- `docs/architecture.md`
- `docs/contracts.md`
- `docs/implementation-roadmap.md`
- `docs/service-boundaries.md`
- `ingestion_service/server/`
- `manager_service/`
- `memory_service/`
- `project_service/client.py`
- `retrieval_service/indexing/service.py`
- `retrieval_service/retrieval/service.py`
- `shared/`
- new tests for app config, indexing, ingestion jobs/server, manager service, project service client/app, retrieval facade, workflow log service
- `workflow_log_service/`

## Cleanup Command

After running tests, clean Python bytecode caches if they appear:

```bash
find . -type d -name '__pycache__' -prune -exec rm -rf {} +
```

Use escalation only if the sandbox blocks an important command. Do not run destructive git commands.
