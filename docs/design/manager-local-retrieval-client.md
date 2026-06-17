# Manager Local Retrieval Client

Section status: implementation accepted for the ninth development loop section.

## Requirement Document

The manager now has a `RetrievalClient` protocol, and the retrieval service now
has an app context. There is still no local adapter that lets a composition root
provide retrieval independently of the compatibility `ProjectDocumentClient`.
That keeps manager retrieval dispatch tied to the project/RAG compatibility
client even though retrieval has its own facade.

This section adds a manager-facing local retrieval client adapter. The adapter
delegates search and delete to a retrieval app context or retrieval service. It
does not solve project policy/scope planning; callers must provide requests in
the retrieval service shape.

Scope:

- Add `LocalRetrievalClient` implementing manager `RetrievalClient` methods.
- Delegate `search` to retrieval service search.
- Delegate `delete_document` to retrieval service delete.
- Keep request mapping minimal and explicit.

Out of scope:

- Manager app wiring to use this client by default.
- Project config/scope lookup for manager public requests.
- Remote retrieval transport.

## Acceptance Criteria

- `LocalRetrievalClient` can be constructed with an object that exposes
  `search` and `delete_document`.
- `LocalRetrievalClient.search(request)` delegates to the retrieval app/service.
- `LocalRetrievalClient.delete_document(request)` delegates to the retrieval
  app/service.
- The adapter is exported from `manager_service.clients`.
- Tests cover direct adapter behavior and `ManagerService` construction with a
  separate retrieval client.
- `progress.md` records the section result.

## Structure Design

Files changed in this section:

```text
manager_service/
  clients.py          local retrieval adapter
  __init__.py         public export

tests/
  test_manager_service.py

docs/
  design/manager-local-retrieval-client.md

progress.md
```

## Class Design

### `LocalRetrievalClient`

Constructor:

- `retrieval: Any`

Methods:

- `search(request) -> Any`
- `delete_document(request) -> Any`

## Implementation Design

1. Add adapter class to `manager_service.clients`.
2. Export it from `manager_service`.
3. Add tests proving manager search/delete route through the local retrieval
   adapter while ingest/status can still use a separate ingestion client.
4. Run manager and retrieval app tests.

## Review Checklist

- The adapter does not import retrieval internals beyond accepting an injected
  object.
- No project config planning is hidden inside this adapter.
- Compatibility `ProjectDocumentClient` adapters remain available.
