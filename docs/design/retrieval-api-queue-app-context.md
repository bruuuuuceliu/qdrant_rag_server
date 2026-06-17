# Retrieval API Queue App Context

Section status: implementation accepted for the next development loop section.

## Requirement Document

The retrieval API queue transport has a consumer and client, but there is no
retrieval-owned app context that starts the consumer around a retrieval service.
Add a minimal queue app context so local split-service composition can run a
retrieval API queue worker independently from manager code.

Scope:

- Add a queue app context under `retrieval_service.server`.
- Compose `RetrievalApiServerContext` with `RetrievalApiQueueConsumer`.
- Support enabled/disabled modes.
- Provide clean shutdown for the consumer and server context.

Out of scope:

- Manager wiring to queue mode.
- Production broker semantics.
- Network transport.
- Retrieval infrastructure factory construction.

## Acceptance Criteria

- `create_queue_app(...)` returns a context with API context, queue consumer,
  enabled flag, and topic.
- Enabled mode starts the queue consumer.
- Disabled mode creates the API context without starting a consumer.
- Shutdown stops the consumer when present and shuts down the API context.
- Tests cover enabled, disabled, and shutdown behavior.
- Docs and `progress.md` record the section result.

## Structure Design

Files changed in this section:

```text
retrieval_service/server/
  app.py             queue app context and factory
  __init__.py        public exports

tests/
  test_retrieval_api_queue_app.py

docs/
  design/retrieval-api-queue-app-context.md
  design/section-design-index.md

progress.md
```

## Class Design

### `RetrievalApiQueueAppContext`

Fields:

- `enabled`
- `topic`
- `api`
- `consumer`

Methods:

- `shutdown()`

## Implementation Design

1. Add `RetrievalApiQueueAppContext` to `retrieval_service.server.app`.
2. Add `create_queue_app(...)` factory.
3. Build a retrieval API server context using the existing `create_app(...)`.
4. Start `RetrievalApiQueueConsumer` only when enabled.
5. Export the queue app context and factory.
6. Add focused tests with fake queue and retrieval service.

## Review Checklist

- No manager imports in retrieval server code.
- No generated transport files are touched.
- Consumer lifecycle mirrors existing ingestion/indexing app context patterns.
