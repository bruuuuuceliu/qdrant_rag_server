# Project Config Scope API Extraction

Status: accepted.

## Requirement

Expose project-owned config/scope planning through a project service API so
manager and retrieval execution paths do not reach directly into gateway
internals or compatibility `RagEngine`.

This is the first migration step toward the target design where manager starts
project tasks and checks project task status, while project service owns
project-document orchestration.

## Acceptance Criteria

- Project service provides a planning API for search, delete, and ingest.
- Planning outputs include project-owned execution inputs such as collection
  name, retrieval config, scope/filter data, and request identifiers.
- Planning API does not import retrieval implementation internals.
- Existing compatibility clients keep working.
- Manager local retrieval composition uses the project planning API instead of
  passing a gateway directly into the retrieval client.
- Focused tests cover search, delete, and ingest planning.

## Structure Design

```text
project_service/planning.py
  ProjectPlanningService
  ProjectSearchPlan
  ProjectDeletePlan
  ProjectIngestPlan

project_service/client.py
  ProjectPlannedRetrievalApiClient uses ProjectPlanningService-compatible API

manager_service/server/app.py
  constructs ProjectPlanningService at the composition root
```

## Class Design

- `ProjectPlanningService` wraps the existing gateway while hiding gateway plan
  shape from manager-facing clients.
- `ProjectSearchPlan` carries search request, project ID, user ID, query text,
  collection name, retrieval config, and retrieval filter.
- `ProjectDeletePlan` carries delete request, project/user/kb/doc IDs, and
  collection name.
- `ProjectIngestPlan` carries ingest request, project/user/kb/doc IDs,
  collection name, retrieval config, and chunker config.

## Implementation Design

1. Add project-owned planning dataclasses and service facade.
2. Refactor project-planned retrieval API client to accept a planning service.
3. Keep a gateway fallback in the retrieval API client during migration.
4. Wire manager app local composition through `ProjectPlanningService`.
5. Add focused planning and client tests.
6. Run focused tests and the full suite.

## Review Notes

- This section does not remove `RagEngine`; it creates the project-owned API
  needed to remove it safely in later sections.
- The planning service is intentionally transport-neutral and can later be
  wrapped by HTTP, gRPC, or queue transport.
- Workflow logging remains outside the project planning path.
