# Manager Remote Retrieval HTTP Client

Status: accepted.

## Requirement

Allow the manager service to call a separately running retrieval service over
the new retrieval HTTP API transport while preserving the existing manager
public API and project-planned retrieval behavior.

The manager still needs project planning before calling retrieval because
project configuration, collection names, visibility filters, and retrieval
config remain owned by project service during this migration. This section only
replaces the retrieval execution adapter after planning.

## Acceptance Criteria

- Manager settings support `MANAGER_RETRIEVAL_CLIENT_MODE=http`.
- Manager settings include retrieval HTTP base URL and response timeout values.
- A remote retrieval HTTP client exposes `search`, `delete_document`, and
  `get_raw_document` payload methods compatible with
  `ProjectPlannedRetrievalApiClient`.
- The remote client sends JSON requests to:
  - `POST /search`
  - `POST /documents/delete`
  - `POST /documents/raw`
- Non-2xx HTTP responses with retrieval envelopes are returned to the caller so
  existing response-envelope error handling remains centralized.
- Invalid or non-object HTTP response bodies raise clear `RuntimeError`
  failures.
- Manager local composition can choose the HTTP retrieval client without
  starting an embedded retrieval API app.
- Focused tests cover config loading, remote client request/response mapping,
  failure handling, and manager composition selection.
- Existing queue and local retrieval modes keep passing.

## Structure Design

```text
configs/manager/config.py
  ManagerSettings.retrieval_http_base_url
  ManagerSettings.retrieval_http_timeout

retrieval_service/server/http_client.py
  RetrievalApiHttpClient

project_service/client.py
  ProjectPlannedRetrievalApiClient reuses any object with the payload methods

manager_service/server/app.py
  MANAGER_RETRIEVAL_CLIENT_MODE=http composition branch

tests/test_retrieval_http_client.py
tests/test_project_service_client.py
tests/test_manager_service.py
```

## Class Design

### `RetrievalApiHttpClient`

Thin async HTTP adapter over retrieval response envelopes.

Constructor fields:

- `base_url`
- `timeout`
- optional injected `http_client` for tests

Methods:

- `search(payload)`
- `delete_document(payload)`
- `get_raw_document(payload)`
- `shutdown()`

Each method returns the response-envelope mapping unchanged.

## Implementation Design

1. Add manager retrieval HTTP settings and env examples.
2. Implement `RetrievalApiHttpClient` using `httpx.AsyncClient` with optional
   client injection.
3. Export the client from `retrieval_service.server`.
4. Update manager composition to support retrieval modes `local`, `queue`, and
   `http`.
5. Ensure HTTP mode requires a local project app for project planning but does
   not start an embedded retrieval API app.
6. Add tests for client behavior and manager composition.
7. Update docs and `progress.md` after focused and full verification pass.

## Review Notes

- This is intentionally a retrieval execution client, not a project client.
- Project planning remains in-process in manager local composition until the
  project service has its own config/scope API.
- The HTTP client returns retrieval envelopes unchanged so
  `ProjectPlannedRetrievalApiClient` remains the single mapping point into
  project-facing `SearchResult` and manager errors.
