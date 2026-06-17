# Retrieval API Import Boundary Guard

Section status: implementation accepted for the next development loop section.

## Requirement Document

The retrieval API contracts and handler are meant to be reusable by future gRPC,
HTTP, or queue transports. They must not start depending on manager,
project-service, ingestion-service, generated protobuf, or concrete transport
modules. A focused import-boundary guard should keep this contract layer clean as
the physical service API work begins.

Scope:

- Add an AST-based import-boundary test for retrieval API contract modules.
- Guard `retrieval_service.retrieval.contracts` and
  `retrieval_service.retrieval.handler`.
- Forbid imports from manager, project, ingestion, generated protobuf, and
  concrete transport server/client modules.

Out of scope:

- Guarding all retrieval internals.
- Rewriting existing compatibility imports outside the retrieval API layer.
- Network transport implementation.

## Acceptance Criteria

- The new test fails if retrieval API contract modules import other service
  internals or generated transport code.
- Existing retrieval API modules pass the guard.
- The guard is included in focused verification.
- `progress.md` and the design index record the section.

## Structure Design

Files changed in this section:

```text
tests/
  test_retrieval_api_import_boundaries.py

docs/
  design/retrieval-api-import-boundary-guard.md
  design/section-design-index.md

progress.md
```

## Class Design

No production classes are introduced. The test module contains:

- guarded file list
- forbidden import prefixes
- import parser helper

## Implementation Design

1. Parse guarded Python files with `ast`.
2. Collect import and import-from module names.
3. Fail if any import starts with a forbidden prefix.
4. Keep the guard targeted so composition roots and compatibility modules remain
   free to import what they need during migration.

## Review Checklist

- The guard does not block retrieval-owned service/facade imports.
- The guard covers the new API contract and handler modules.
- The forbidden list is narrow enough to avoid false positives while blocking
  the dependencies this layer must not take.
