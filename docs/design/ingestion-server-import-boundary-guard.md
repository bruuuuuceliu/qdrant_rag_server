# Ingestion Server Import Boundary Guard

Section status: implementation accepted for the fifteenth development loop section.

## Requirement Document

The ingestion server queue consumer now accepts jobs, prepares neutral chunks,
and publishes retrieval indexing commands. It should stay independent of
project/RAG engine internals and retrieval implementation internals. A focused
import-boundary guard will keep the server queue modules constrained to shared
contracts, ingestion-owned code, and queue abstractions.

Scope:

- Add an AST import-boundary test for ingestion server queue modules.
- Guard `ingestion_service/server/app.py` and `consumer.py`.
- Forbid direct imports from project service, manager service, retrieval service,
  and Qdrant client.

Out of scope:

- Guarding standalone worker composition, which intentionally imports the
  compatibility project client during migration.
- Full package-wide architecture linting.

## Acceptance Criteria

- The boundary test fails if ingestion server queue modules import forbidden
  service internals.
- Current ingestion server queue modules pass.
- `progress.md` records the section result.

## Structure Design

Files changed in this section:

```text
tests/
  test_ingestion_server_import_boundaries.py

docs/
  design/ingestion-server-import-boundary-guard.md

progress.md
```

## Implementation Design

1. Add AST import collector helper.
2. Guard ingestion server app and consumer files.
3. Add forbidden prefixes for project, manager, retrieval, and Qdrant internals.
4. Run boundary and ingestion server tests.

## Review Checklist

- Standalone worker composition remains outside this guard.
- The consumer can still publish queue payloads without importing retrieval
  implementation modules.
