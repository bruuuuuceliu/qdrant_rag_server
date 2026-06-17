# Manager Local Retrieval Composition

Section status: implementation accepted for the nineteenth development loop section.

## Requirement Document

The manager app now wires explicit split clients, but local retrieval still uses
the `ProjectDocumentRetrievalClient` compatibility adapter. That means manager
search/delete still call the project-document client even though retrieval has a
facade and app context. The missing piece is a local retrieval adapter that uses
project gateway planning for public request shape and then delegates execution
to the retrieval facade.

This section moves local manager retrieval composition one step closer to the
target boundary while keeping project config/scope planning in the project
service.

Scope:

- Add a project-service local retrieval client that implements manager-facing
  retrieval methods.
- Use project gateway `prepare_search` and `prepare_delete` for scope/config.
- Execute search/delete through the retrieval service facade.
- Wire manager local mode to use this adapter when the local project app is
  available.

Out of scope:

- Remote retrieval transport.
- Removing project config/scope planning from project service.
- Changing public manager request DTOs.

## Acceptance Criteria

- Local manager app mode wires retrieval through the local retrieval facade
  adapter.
- gRPC project-client mode keeps the project-document retrieval compatibility
  adapter.
- Search results are returned in the existing project `SearchResult` shape.
- Delete delegates to retrieval facade delete with collection/config from the
  project gateway plan.
- Tests cover adapter search/delete and manager local composition.
- `progress.md` records the section result.

## Structure Design

Files changed in this section:

```text
project_service/
  client.py          project-planned local retrieval adapter
  rag/engine.py      expose retrieval facade for local composition

manager_service/server/
  app.py             local retrieval client wiring

tests/
  test_project_service_client.py
  test_manager_service.py

docs/
  design/manager-local-retrieval-composition.md

progress.md
```

## Class Design

### `ProjectPlannedRetrievalClient`

Constructor:

- `gateway`
- `retrieval_service`

Methods:

- `search(request) -> SearchResult`
- `delete_document(request) -> None`

## Implementation Design

1. Add adapter to `project_service.client`.
2. Add a read-only `retrieval_service` property to `RagEngine` for local
   composition.
3. Wire manager local mode to use `ProjectPlannedRetrievalClient`.
4. Keep remote project mode on compatibility adapter.
5. Add focused tests and run manager/project client tests.

## Review Checklist

- Manager core remains free of project/retrieval internals.
- Project service keeps config/scope planning ownership.
- Retrieval execution no longer goes through full project-document client in
  local manager composition.
