# Retrieval API Server Context

Section status: implementation accepted for the next development loop section.

## Requirement Document

The retrieval service has a transport-neutral API handler, but it still lacks a
retrieval-owned server composition context. The current protobuf source models
the compatibility `RagService`, so this section should not mutate generated
gRPC files. Instead, add a minimal server context that exposes retrieval API
handler methods and can be wrapped by future gRPC, HTTP, or queue transports.

Scope:

- Add `retrieval_service.server` with a retrieval API server context.
- Compose `RetrievalAppContext` and `RetrievalApiHandler` from an injected
  retrieval service.
- Expose async `search`, `delete_document`, and `get_raw_document` methods that
  accept plain payload mappings and return response-envelope mappings.
- Provide a safe shutdown path.

Out of scope:

- gRPC, HTTP, or protobuf generation.
- Manager remote retrieval client wiring.
- Retrieval infrastructure factory construction.
- Authentication, tracing, rate limits, or live server startup.

## Acceptance Criteria

- `retrieval_service.server.create_app(retrieval_service=...)` returns a context
  with an app context and handler.
- The context delegates search, delete, and raw-document payload mappings
  through `RetrievalApiHandler`.
- The context accepts explicit fallback request IDs.
- Shutdown delegates to the retrieval app context.
- Tests cover delegation and shutdown behavior.
- Docs and `progress.md` record the section result.

## Structure Design

Files changed in this section:

```text
retrieval_service/server/
  __init__.py        public server-context exports
  app.py             retrieval API server context and factory

tests/
  test_retrieval_api_server.py

docs/
  design/retrieval-api-server-context.md
  design/section-design-index.md

progress.md
```

## Class Design

### `RetrievalApiServerContext`

Fields:

- `app`
- `handler`

Methods:

- `search(payload, fallback_request_id)`
- `delete_document(payload, fallback_request_id)`
- `get_raw_document(payload, fallback_request_id)`
- `shutdown()`

## Implementation Design

1. Add `retrieval_service/server/app.py`.
2. Build `RetrievalAppContext` through `retrieval_service.retrieval.create_app`.
3. Build `RetrievalApiHandler` around the app context.
4. Expose thin async methods for transport adapters.
5. Export the context and factory from `retrieval_service.server`.
6. Add tests using a fake retrieval service.
7. Run retrieval API/server/docs focused tests.

## Review Checklist

- No generated gRPC files are edited.
- The server context imports only retrieval-owned modules.
- The context does not construct Qdrant, embeddings, or storage infrastructure.
- The public surface accepts and returns plain mappings.
