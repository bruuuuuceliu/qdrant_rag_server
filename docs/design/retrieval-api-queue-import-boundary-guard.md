# Retrieval API Queue Import Boundary Guard

Section status: implementation accepted for the next development loop section.

## Requirement Document

The retrieval API queue transport is a retrieval-owned transport adapter over
`shared.queue`. It must remain independent from manager, project, ingestion,
generated protobuf, and concrete network transport code. Extend the retrieval
API import-boundary guard to cover the queue transport module.

Scope:

- Add `retrieval_service.server.queue` to the retrieval API import-boundary
  guarded files.
- Keep the forbidden import list unchanged.
- Record the accepted guard in docs and progress.

Out of scope:

- Guarding future explicit gRPC/HTTP adapter modules.
- Rewriting existing compatibility imports outside retrieval API/server queue
  modules.

## Acceptance Criteria

- The boundary test fails if retrieval API queue transport imports manager,
  project, ingestion, generated transport code, or `grpc`.
- Current retrieval API queue modules pass the guard.
- Focused boundary tests pass.
- `progress.md` and section docs record the section.

## Structure Design

Files changed in this section:

```text
tests/
  test_retrieval_api_import_boundaries.py

docs/
  design/retrieval-api-queue-import-boundary-guard.md
  design/section-design-index.md

progress.md
```

## Implementation Design

1. Add `retrieval_service/server/queue.py` to `GUARDED_FILES`.
2. Keep the existing AST import parser and forbidden prefix list.
3. Run focused boundary and retrieval API queue tests.

## Review Checklist

- Queue transport can import `shared.queue`.
- Queue transport remains free of manager/project/ingestion dependencies.
- No generated transport files are touched.
