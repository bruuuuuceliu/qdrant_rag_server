# Manager Context Ingestion Jobs

Section status: implementation accepted for the eighteenth development loop section.

## Requirement Document

The manager app can now use `LocalIngestionClient` with the embedded ingestion
job repository, but callers need to reach through `context.ingestion_app.jobs`
to inspect the repository. A small context property makes the owned job state
explicit without changing runtime behavior.

Scope:

- Add `ingestion_jobs` property to `ManagerAppContext`.
- Return the embedded ingestion app repository when available.
- Return `None` for external ingestion worker mode.

Out of scope:

- New status APIs.
- Remote ingestion job lookup.
- Changing manager service behavior.

## Acceptance Criteria

- `ManagerAppContext.ingestion_jobs` returns the embedded ingestion repository.
- `ManagerAppContext.ingestion_jobs` is `None` in external ingestion mode.
- Manager app tests cover both paths.
- `progress.md` records the section result.

## Structure Design

Files changed in this section:

```text
manager_service/server/
  app.py

tests/
  test_manager_service.py

docs/
  design/manager-context-ingestion-jobs.md

progress.md
```

## Implementation Design

1. Add property to `ManagerAppContext`.
2. Update manager app tests for embedded and external modes.
3. Run manager tests.

## Review Checklist

- The property is read-only and does not create jobs.
- External worker mode remains explicit with `None`.
