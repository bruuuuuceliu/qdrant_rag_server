# Retrieval Server Import Boundary Guard

Section status: implementation accepted for the next development loop section.

## Requirement Document

The retrieval API server context is the retrieval-owned service surface that
future network adapters will wrap. It should remain free of manager,
project-service, ingestion-service, generated protobuf, and concrete transport
imports. A narrow import-boundary guard should protect this layer before adding
gRPC or HTTP adapters.

Scope:

- Extend the retrieval API import-boundary test to cover
  `retrieval_service.server.app`.
- Keep the guard focused on the transport-neutral retrieval API/server layer.
- Record the accepted guard in docs and progress.

Out of scope:

- Blocking imports in future network adapter modules.
- Rewriting existing compatibility gRPC imports.
- Adding network transport.

## Acceptance Criteria

- The boundary test fails if the retrieval server context imports manager,
  project, ingestion, generated transport code, or `grpc`.
- The current retrieval server context passes the guard.
- Focused boundary tests pass.
- `progress.md` and section docs record the section.

## Structure Design

Files changed in this section:

```text
tests/
  test_retrieval_api_import_boundaries.py

docs/
  design/retrieval-server-import-boundary-guard.md
  design/section-design-index.md

progress.md
```

## Class Design

No production classes are introduced.

## Implementation Design

1. Add `retrieval_service/server/app.py` to the guarded file list.
2. Keep the existing forbidden prefix set.
3. Update the test name to reflect API and server context coverage.
4. Run the focused boundary/API suite.

## Review Checklist

- Guard remains targeted to transport-neutral modules.
- Future explicit gRPC/HTTP adapters can live outside the guarded file list.
- No generated files are touched.
