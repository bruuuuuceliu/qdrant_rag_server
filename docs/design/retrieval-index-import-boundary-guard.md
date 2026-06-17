# Retrieval Index Import Boundary Guard

Section status: implementation accepted for the fourteenth development loop section.

## Requirement Document

The retrieval indexing queue command and consumer should remain retrieval-owned
and transport-neutral. Future edits could accidentally import manager,
project-service, or ingestion implementation internals into these modules. A
small import-boundary test should prevent that regression while allowing the
ingestion-to-retrieval publication boundary to remain queue-based.

Scope:

- Add an AST import-boundary test for retrieval indexing queue modules.
- Guard `retrieval_service/indexing/commands.py`, `consumer.py`, and `app.py`.
- Forbid direct imports from manager, project service, and ingestion service.

Out of scope:

- Full architecture linting across every retrieval module.
- Blocking retrieval indexing imports of retrieval schema/service modules.

## Acceptance Criteria

- The boundary test fails if retrieval indexing queue modules import manager,
  project service, or ingestion service modules.
- Current retrieval indexing queue modules pass.
- `progress.md` records the section result.

## Structure Design

Files changed in this section:

```text
tests/
  test_retrieval_index_import_boundaries.py

docs/
  design/retrieval-index-import-boundary-guard.md

progress.md
```

## Implementation Design

1. Add AST import collector helper.
2. Guard retrieval indexing queue files.
3. Add forbidden prefixes for manager, project, and ingestion services.
4. Run boundary and retrieval index tests.

## Review Checklist

- The guard is narrow and does not block retrieval-owned indexing imports.
- The failure message names the violating file and import.
