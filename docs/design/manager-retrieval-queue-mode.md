# Manager Retrieval Queue Mode

Section status: implementation accepted for the next development loop section.

## Requirement Document

Manager local mode can call the retrieval API server context in-process, and the
retrieval service now has a queue request/response transport. Add manager
configuration and wiring so local split-service development can route retrieval
search/delete through `retrieval.api.requests` while preserving the current
in-process default.

Scope:

- Add manager retrieval client mode settings.
- Support `MANAGER_RETRIEVAL_CLIENT_MODE=local|queue`.
- Add `MANAGER_RETRIEVAL_TOPIC` and `MANAGER_RETRIEVAL_RESPONSE_TIMEOUT`.
- In local project mode, build either an in-process retrieval API context or a
  queue-backed retrieval API client.
- For queue mode, start an embedded retrieval queue app while local project app
  is available.

Out of scope:

- Remote queue broker deployment.
- gRPC/HTTP retrieval transport.
- Remote project/RAG mode retrieval queue wiring.
- Raw-document manager route.

## Acceptance Criteria

- Default manager local mode keeps in-process retrieval API execution.
- Queue mode creates a `RetrievalApiQueueClient` and embedded retrieval queue
  app.
- Queue mode uses the configured retrieval topic and timeout.
- Invalid retrieval client modes fail fast with a clear `ValueError`.
- Tests cover default mode, queue mode, and invalid mode.
- Config examples, docs, and `progress.md` record the section result.

## Structure Design

Files changed in this section:

```text
configs/manager/
  config.py
  local.env.example

manager_service/server/
  app.py

tests/
  test_app_config.py
  test_manager_service.py

docs/
  design/manager-retrieval-queue-mode.md
  design/section-design-index.md

progress.md
```

## Class Design

No new production classes are required. `ManagerSettings` gains:

- `retrieval_client_mode`
- `retrieval_topic`
- `retrieval_response_timeout`

## Implementation Design

1. Extend `ManagerSettings` and loader.
2. Add example env variables under `configs/manager`.
3. Update manager app local composition:
   - `local`: use direct `RetrievalApiServerContext`.
   - `queue`: start `create_retrieval_queue_app(...)` and use
     `RetrievalApiQueueClient`.
4. Keep remote project mode unchanged.
5. Add focused tests.

## Review Checklist

- Manager core still depends only on manager-facing client protocols.
- Queue mode remains local-composition only until a production broker adapter is
  configured deliberately.
- Shutdown closes embedded retrieval queue app exactly once.
