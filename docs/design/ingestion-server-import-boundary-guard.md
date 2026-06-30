# Ingestion Server Import Boundary Guard

Section status: implementation accepted for the fifteenth development loop section.

## Requirement Document

The ingestion broker helper accepts task-service commands, prepares neutral
chunks, and publishes helper results. It should stay independent of project/RAG
engine internals and retrieval implementation internals. A focused
import-boundary guard keeps ingestion server modules constrained to shared
contracts and ingestion-owned code.

Scope:

- Add an AST import-boundary test for ingestion server modules.
- Guard `broker_runtime.py`, `domain_handler.py`, `helper_app.py`, and
  `worker.py`.
- Forbid direct imports from project service, manager service, retrieval service,
  and Qdrant client.

Out of scope:

- Full package-wide architecture linting beyond the focused ingestion server
  guard.

## Acceptance Criteria

- The boundary test fails if ingestion server modules import forbidden
  service internals.
- Current ingestion server modules pass.
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
2. Guard current ingestion server files.
3. Add forbidden prefixes for project, manager, retrieval, and Qdrant internals.
4. Run boundary and ingestion server tests.

## Review Checklist

- Standalone worker composition remains inside the guard unless it only imports
  shared contracts and ingestion-owned modules.
- The helper can still publish broker payloads without importing retrieval
  implementation modules.
