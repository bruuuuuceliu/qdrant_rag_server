# Retrieval Index App Context

Section status: implementation accepted for the sixth development loop section.

## Requirement Document

The retrieval indexing consumer can process `retrieval.index.requests`, but it
is currently only a class. A small app context is needed so future local service
composition can start and stop the retrieval indexing worker consistently, just
as ingestion has a server app context.

This section adds that context without constructing embeddings, Qdrant, or
project configuration. Those dependencies remain injected so infrastructure
composition can be added later without mixing setup code into the queue worker.

Scope:

- Add `retrieval_service.indexing.app.create_app(...)`.
- Start `RetrievalIndexConsumer` when enabled.
- Provide a shutdown method that stops the consumer.
- Keep dependencies injected: queue and `IndexingService`.

Out of scope:

- Building `IndexingService` from configs.
- Starting a standalone retrieval process.
- Wiring Qdrant, embeddings, sparse encoders, or project config lookup.

## Acceptance Criteria

- `create_app(queue=..., indexing_service=...)` returns a context with topic,
  enabled state, and consumer reference.
- Enabled app starts a `RetrievalIndexConsumer`.
- Disabled app has no consumer.
- Shutdown stops the consumer when present.
- Tests cover enabled and disabled app creation.
- `progress.md` records the section result.

## Structure Design

Files changed in this section:

```text
retrieval_service/indexing/
  app.py             indexing app context and factory
  __init__.py        public export

tests/
  test_retrieval_index_app.py

docs/
  design/retrieval-index-app-context.md

progress.md
```

## Class Design

### `RetrievalIndexAppContext`

Fields:

- `enabled`
- `topic`
- `consumer`

Methods:

- `shutdown()`

## Implementation Design

1. Add dataclass context in `retrieval_service.indexing.app`.
2. Add `create_app(...)` factory with optional `enabled` and `topic` settings.
3. Export `RetrievalIndexAppContext` and `create_app`.
4. Add focused app tests.
5. Run retrieval index consumer/app tests.

## Review Checklist

- App context does not import infrastructure factories.
- Disabled mode is side-effect free.
- Shutdown is idempotent through the consumer stop path.
