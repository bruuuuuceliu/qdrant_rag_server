# Manager Project Task Routing

Status: accepted.

## Requirement

Route project-document operations through the project service as the domain task
executor. The manager should start project tasks, check project task status, and
return results without treating ingestion or retrieval as manager-owned request
targets.

This section aligns the manager-facing path with the corrected design:

```text
Client -> Manager -> Project Service -> capability services -> Project Service
       -> Manager -> Client
```

Workflow logging remains observational and is not part of the business path.

## Acceptance Criteria

- Manager router targets `project_service` for project-document ingest, search,
  delete, and status operations.
- Manager service delegates normal project-document operations to a
  project-document task client.
- Split ingestion/retrieval clients remain available only as compatibility
  fallback when no project client is provided.
- Manager local composition passes the project service client as the normal
  executor instead of wiring retrieval/ingestion clients into the manager.
- Project local client exposes task-oriented aliases for ingest start, search,
  and status while preserving existing compatibility methods.
- Workflow log and memory placeholders stay out of the project-document path.

## Structure Design

```text
manager_service/routing/router.py
  ManagerRouter routes project_document operations to ServiceTarget.PROJECT

manager_service/service.py
  ManagerService prefers ProjectDocumentClient for project-document operations
  split clients are legacy fallback only

project_service/client.py
  LocalProjectServiceClient exposes task-named project operations

manager_service/server/app.py
  local composition gives ManagerService the project client as executor
```

## Class Design

- `ManagerRouter` owns public route decisions and identifies the domain owner
  for project-document work as `ServiceTarget.PROJECT`.
- `ManagerService` remains transport-neutral and depends on a
  `ProjectDocumentClient` protocol for normal project-document execution.
- `LocalProjectServiceClient` exposes:
  - `start_document_ingest_task(...)`
  - `search_documents(...)`
  - `get_document_task_status(...)`

Existing `ingest`, `search`, and `ingest_status` methods remain as aliases while
older callers migrate.

## Implementation Design

1. Change project-document router decisions to target project service.
2. Update manager dispatch to prefer task-named project client methods when
   present.
3. Keep ingestion/retrieval split clients as fallback for compatibility tests
   and old callers.
4. Stop manager app from injecting retrieval/ingestion clients into the manager
   for the normal local path.
5. Add task-named local project service methods backed by the current engine.
6. Update tests to assert project-service ownership.
7. Run focused manager/project tests and the full suite.

## Review Notes

- This section changes manager-facing ownership only. The project service still
  uses compatibility engine internals until later sections replace ingestion
  callback and retrieval execution paths.
- The embedded ingestion worker and retrieval API apps may still be started by
  local composition, but manager no longer owns them as project-document targets.
- Queue-based direct manager ingest remains a legacy compatibility path when an
  explicit `ingest_queue` is supplied.
