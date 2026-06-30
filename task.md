# Current Task: Garbage Cleanup For Broker-First Multi-Server Runtime

Date: 2026-06-30

## Goal

Clean this repository so the code matches the current multi-server design:

- Independent top-level services and nodes.
- Runtime communication through Redpanda topics.
- Redis for task status/read-model data.
- SQLite for durable service-owned local state.
- No runtime shortcuts through embedded services, in-memory queues, local-only
  message buses, direct HTTP service transports, or cross-service internal
  imports.

The cleanup is not a feature expansion. It is removal of old design garbage and
alignment of existing code, configs, tests, and docs with the current runtime.

## Required References

Read and keep aligned with:

- `docs/development.md`
- `progress.md`
- `plan.md`
- `docs/contracts.md`
- `docs/service-boundaries.md`
- `docs/implementation-roadmap.md`

`progress.md` is the current control document for implementation state.

## Target Runtime Shape

Current intended flow:

1. Manager accepts public requests and publishes task intake.
2. Task manager normalizes intake, publishes `task.requests`, and updates Redis
   status from task events/results.
3. Task service consumes `task.requests`, requests project plans, dispatches
   helper work, fans in results, retries/dead-letters when needed, and publishes
   `task.events`/`task.results`.
4. Project service consumes `project.plan.requests` and publishes
   `project.plan.results`.
5. Helpers consume only their helper command topics and publish helper results:
   ingestion, retrieval, retrieval-index, storage, SQLite/database helper.
6. Workflow log observes audit/domain events asynchronously.

## Garbage To Remove Or Keep Removed

Remove code, config, docs, and tests that keep these old designs alive:

- `shared.queue`, `LocalQueueBroker`, SQLite queue, or in-memory queue runtime
  transports.
- Direct manager-to-project, manager-to-ingestion, or manager-to-retrieval
  client modes.
- Direct retrieval HTTP/API transport modules for service-to-service runtime.
- Root `server/` compatibility runtime.
- Project RAG monolith paths under old `project_service/rag` or
  `retrieval_service/rag` ownership.
- Project-planning aliases using `domain.project.commands` or
  `domain.project.results`.
- Shared queued-ingest request/response DTOs for old manager-to-ingestion
  request/response queues.
- Stale tests that assert deleted modules still exist.

Do not delete legitimate external HTTP usage for providers/backends such as
Qdrant, OpenRouter/OpenAI-compatible APIs, S3-compatible storage, or user source
URL loading. Those are not service-to-service runtime transports.

## Completed In Current Cleanup Pass

- Rewrote this task file to focus only on the current cleanup task.
- Removed project-planning `domain.project.*` runtime aliases from shared topic
  constants, project-service config fallback, task-service project-result
  consumers, env examples, and tests.
- Deleted the obsolete shared queued-ingest contract from `shared/contracts`.
- Moved ingestion helper plan parsing into
  `ingestion_service.server.broker_runtime`, where ingestion owns it.
- Fixed stale tests that referenced deleted workflow-log server modules.
- Fixed missing `Path` imports in tests that blocked verification.
- Moved generated gRPC stubs from project-service ownership to
  `shared.transport.grpc.generated`.
- Deleted the stale `project_service.server` transport namespace.
- Removed project-service imports of retrieval internals by moving placement
  scope to a project-owned DTO and replacing retrieval placement test imports
  with local fakes.
- Removed project adapter ingest hooks and deleted the old
  `retrieval_service.ingest` compatibility pipeline that embedded ingestion and
  project adapter behavior.
- Replaced retrieval and manager tests that imported project/retrieval internals
  with service-local fakes or shared contracts.
- Removed stale `Base*` project schema aliases and retrieval
  `BaseProjectConfig` compatibility export.
- Tightened project import-boundary tests to scan the full `project_service`
  package for forbidden service imports.
- Confirmed no source imports remain for deleted `shared.queue`,
  `LocalQueueBroker`, retrieval HTTP transport modules, deleted queued-ingest
  DTOs, deleted retrieval ingest compatibility modules, or direct
  project/retrieval/ingestion cross-service imports.

## Verification

Latest focused cleanup verification:

```bash
pytest -q tests/test_shared_contracts.py tests/test_message_contracts.py \
  tests/ingestion/test_broker_runtime.py tests/ingestion/test_service.py \
  tests/task_manager tests/task_service tests/project tests/manager tests/broker \
  tests/retrieval/test_indexing_service.py tests/retrieval/test_service_facade.py \
  tests/retrieval/test_api_import_boundaries.py \
  tests/retrieval/test_index_import_boundaries.py \
  tests/integration/test_broker_first_message_flow.py
# 177 passed, 1 skipped
```

Latest full verification:

```bash
pytest -q
# 314 passed, 4 skipped
```

Diff sanity check:

```bash
git diff --check
# passed
```

## Remaining Cleanup Work

- Keep tightening import-boundary tests around the manager gRPC compatibility
  adapter.
- Add stronger live Redpanda + Redis integration coverage for task status
  transitions.
- Continue deleting stale tests/docs when their source modules are removed.
- Keep `progress.md` current after each cleanup step.

## Working Rules

- Preserve user changes and do not revert unrelated dirty worktree changes.
- Remove compatibility shims only when the replacement broker-first path exists
  and tests pass.
- Keep shared code limited to contracts, schemas, protocol clients, error
  codes, correlation IDs, and generic utilities.
- Keep runtime behavior in the owning service or node folder.
- Run focused tests before full verification after meaningful cleanup.
