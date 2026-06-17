# Manager Retrieval API Client

Section status: implementation accepted for the next development loop section.

## Requirement Document

Local manager retrieval composition currently uses `ProjectPlannedRetrievalClient`
to combine project gateway planning with direct retrieval facade calls. The
retrieval service now has a server context that accepts payload mappings and
returns response envelopes. Manager local mode should move one step closer to a
physical service boundary by executing search/delete through that server context
instead of calling the retrieval facade directly.

Scope:

- Add a project-planned retrieval API client for manager-facing search/delete.
- Keep project gateway planning in project service.
- Send retrieval execution payloads to `retrieval_service.server` context
  methods.
- Map successful response envelopes back to existing `SearchResult`/`None`
  manager-facing results.
- Raise clear runtime errors for failed retrieval response envelopes.
- Wire manager local composition through the retrieval server context.

Out of scope:

- Network transport.
- Removing project planning from local manager composition.
- Changing manager public request DTOs.
- Adding raw-document manager routes.

## Acceptance Criteria

- The new client prepares search/delete through the project gateway.
- Search sends a payload to the retrieval API server context and returns a
  `SearchResult`.
- Delete sends a payload to the retrieval API server context and returns `None`
  on success.
- Failed response envelopes raise a clear `RuntimeError`.
- Local manager app mode builds a retrieval server context and uses the new
  client for retrieval dispatch.
- Remote project/RAG mode keeps the compatibility adapter.
- Tests cover search/delete, failure handling, and manager local composition.
- Docs and `progress.md` record the section result.

## Structure Design

Files changed in this section:

```text
project_service/
  client.py          project-planned retrieval API client

manager_service/server/
  app.py             local retrieval server context wiring

tests/
  test_project_service_client.py
  test_manager_service.py

docs/
  design/manager-retrieval-api-client.md
  design/section-design-index.md

progress.md
```

## Class Design

### `ProjectPlannedRetrievalApiClient`

Constructor:

- `gateway`
- `retrieval_api`

Methods:

- `search(request) -> SearchResult`
- `delete_document(request) -> None`

Private helpers:

- `_ensure_ok(response)`
- `_request_id(prefix, plan)`

## Implementation Design

1. Add the new client to `project_service.client` next to the existing direct
   facade adapter.
2. Build search/delete payloads from project gateway plans.
3. Include request IDs that are stable enough for logs and tests.
4. Convert successful search response mappings into `SearchResult`.
5. Raise `RuntimeError` with error code/message for failed envelopes.
6. In manager local mode, create `retrieval_service.server` app around the local
   retrieval service and inject `ProjectPlannedRetrievalApiClient`.
7. Add shutdown handling for the retrieval API context.
8. Update focused tests and docs.

## Review Checklist

- Manager core remains unaware of project/retrieval implementation internals.
- Project planning remains in project service.
- Retrieval execution crosses the retrieval server payload boundary.
- Remote compatibility mode behavior is unchanged.
