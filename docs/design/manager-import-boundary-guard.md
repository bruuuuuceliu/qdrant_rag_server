# Manager Import Boundary Guard

Section status: implementation accepted for the eleventh development loop section.

## Requirement Document

The manager core now publishes task intake and reads Redis task status. This
boundary can regress if future edits import parser, Qdrant, embedding,
retrieval, or project/RAG internals into manager core modules. The repo needs a
small automated guard that keeps manager service core code thin.

Scope:

- Add an import-boundary test for manager core modules.
- Guard `manager_service.service` and `manager_service.server.app` against imports
  from service implementation internals.
- Keep manager composition limited to injected broker and Redis dependencies.

Out of scope:

- Full architectural lint framework.
- Enforcing boundaries across every package.
- Full runtime dependency validation.

## Acceptance Criteria

- A test parses manager core files with `ast`.
- The test fails if manager core imports project service, retrieval service,
  ingestion internals, Qdrant, parser, embedding, or RAG engine modules.
- Current manager core passes the boundary guard.
- `progress.md` records the section result.

## Structure Design

Files changed in this section:

```text
tests/
  test_manager_import_boundaries.py

docs/
  design/manager-import-boundary-guard.md

progress.md
```

## Implementation Design

1. Add an AST helper that collects `import` and `from ... import ...` module
   roots from target files.
2. Define guarded files: `manager_service/service.py` and
   `manager_service/server/app.py`.
3. Define forbidden module prefixes for implementation internals.
4. Add a focused test with clear failure output.
5. Run the boundary test and manager tests.

## Review Checklist

- The guard is narrow enough not to block broker/Redis composition.
- The guard is broad enough to catch direct dependency regressions in manager
  core modules.
- The test is simple and does not require third-party lint tools.
