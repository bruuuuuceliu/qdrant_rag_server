# Retrieval Service App Context

Section status: implementation accepted for the eighth development loop section.

## Requirement Document

`RetrievalService` owns search, delete, and raw-document operations, but there
is no retrieval app context that exposes the service as an independently
composable runtime object. The retrieval service needs a minimal app context
that can be injected into the Redpanda helper worker and tests.

Scope:

- Add a retrieval app context around an injected `RetrievalService`.
- Provide explicit methods for `search`, `delete_document`, and
  `get_raw_document` delegation.
- Keep infrastructure construction out of this section.

Out of scope:

- Network retrieval server transport outside the Redpanda helper flow.
- Manager remote retrieval clients.
- Qdrant/embedding factory wiring.

## Acceptance Criteria

- `retrieval_service.retrieval.create_app(retrieval_service=...)` returns a
  context with the injected service.
- The context delegates search/delete/raw-document calls to the service.
- Shutdown is available and safe even when no underlying service shutdown hook
  exists.
- Tests cover delegation and shutdown behavior.
- `progress.md` records the section result.

## Structure Design

Files changed in this section:

```text
retrieval_service/retrieval/
  app.py             retrieval app context and factory
  __init__.py        public exports

tests/
  test_retrieval_service_app.py

docs/
  design/retrieval-service-app-context.md

progress.md
```

## Class Design

### `RetrievalAppContext`

Fields:

- `retrieval_service`

Methods:

- `search(request)`
- `delete_document(request)`
- `get_raw_document(request)`
- `shutdown()`

## Implementation Design

1. Add `RetrievalAppContext` dataclass.
2. Add `create_app(retrieval_service=...)` factory.
3. Add simple delegation methods.
4. Export app context and factory.
5. Add focused app tests.
6. Run retrieval facade/app tests.

## Review Checklist

- No infrastructure factories are introduced.
- The context delegates only retrieval-owned operations.
- The public retrieval package remains import-stable.
