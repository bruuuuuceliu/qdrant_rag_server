# Project Document Task Service

Status: accepted; capability extraction completed.

Current note: `ProjectDocumentTaskService` now depends on project-facing
ingestion and retrieval capability clients. Temporary `RagEngine` method calls
are isolated in `project_service.capabilities` compatibility adapters instead
of living in the task orchestration service.

## Requirement

Create a project-owned task orchestration surface for project-document work.
Manager should call project service as the executor, and project service should
own the planning-to-capability handoff behind a clear task API.

This section does not remove the compatibility engine yet. It creates the
project service boundary where later sections can replace engine internals with
generic ingestion and retrieval/database capability calls.

## Acceptance Criteria

- Project service provides a dedicated project-document task service.
- Task service exposes task-oriented methods for ingest start, search, status,
  and delete.
- Local project client delegates through the task service instead of directly
  combining gateway and engine calls.
- Planning outputs retain enough raw compatibility context for temporary
  adapter delegation while exposing project-owned fields for new callers.
- Existing local and remote project client behavior remains compatible.
- Focused tests cover project task orchestration.

## Structure Design

```text
project_service/tasks.py
  ProjectDocumentTaskService

project_service/capabilities.py
  ProjectIngestionCapability
  ProjectRetrievalCapability
  CompatibilityIngestionCapability
  CompatibilityRetrievalCapability

project_service/planning.py
  ProjectSearchPlan.raw_plan
  ProjectDeletePlan.raw_plan
  ProjectIngestPlan.raw_plan

project_service/client.py
  LocalProjectServiceClient delegates manager-facing calls to task service
```

## Class Design

- `ProjectDocumentTaskService` owns the task-oriented API:
  - `start_document_ingest_task(...)`
  - `search_documents(...)`
  - `get_document_task_status(...)`
  - `delete_document(...)`
- The service composes a planning API, an ingestion capability client, and a
  retrieval capability client.
- Compatibility aliases `ingest`, `search`, and `ingest_status` remain so older
  callers do not break during migration.

## Implementation Design

1. Add `ProjectDocumentTaskService` as the project-owned orchestration surface.
2. Extend planning dataclasses with `raw_plan` to support temporary engine
   delegation.
3. Refactor `LocalProjectServiceClient` to delegate through the task service.
4. Keep existing project client behavior and mapping request support.
5. Add focused tests for ingest, search, status, and delete orchestration.
6. Run focused project tests, manager tests, boundary tests, and the full suite.

## Review Notes

- This is an internal project-service boundary improvement. It does not yet
  make ingestion generic or remove the engine's indexing pipeline.
- Remaining compatibility executor dependencies are isolated in local adapters;
  the next extraction should replace those adapters with physical ingestion and
  retrieval/database transports.
- Workflow log remains event-only and outside the project request path.
