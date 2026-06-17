# Manager Local Ingestion Client

Section status: implementation accepted for the tenth development loop section.

## Requirement Document

The manager has an `IngestionClient` protocol, but the only concrete adapter is
the compatibility `ProjectDocumentIngestionClient`. Ingestion job status is
already owned by `ingestion_service.jobs`, so manager construction should be
able to use an ingestion-specific local client for status while keeping direct
ingest execution explicit during migration.

This section adds a small local ingestion client adapter. It delegates direct
ingest to an injected callable/client and reads status from an injected job
repository. It does not claim that `IngestionService.process(...)` is a complete
public ingest API.

Scope:

- Add `LocalIngestionClient` implementing manager `IngestionClient`.
- Delegate `ingest(request)` to an injected object with `ingest`.
- Resolve `ingest_status(job_id)` from an ingestion job repository.
- Return a shared `IngestJobResult` for repository-backed statuses.

Out of scope:

- Replacing direct ingest execution with ingestion-owned indexing completion.
- Manager app wiring to use this client by default.
- Remote ingestion transport.

## Acceptance Criteria

- `LocalIngestionClient` can be constructed with an ingest executor and job
  repository.
- `ingest(request)` delegates to the executor.
- `ingest_status(job_id)` returns a shared `IngestJobResult` when a job exists.
- Missing jobs return a pending shared `IngestJobResult` with the requested job
  ID.
- The adapter is exported from `manager_service`.
- Tests cover adapter behavior and `ManagerService` construction with local
  ingestion and retrieval clients.
- `progress.md` records the section result.

## Structure Design

Files changed in this section:

```text
manager_service/
  clients.py          local ingestion adapter
  __init__.py         public export

tests/
  test_manager_service.py

docs/
  design/manager-local-ingestion-client.md

progress.md
```

## Class Design

### `LocalIngestionClient`

Constructor:

- `ingestion: Any`
- `jobs: Any`

Methods:

- `ingest(request) -> Any`
- `ingest_status(job_id) -> IngestJobResult`

## Implementation Design

1. Add adapter class to `manager_service.clients`.
2. Export it from `manager_service`.
3. Convert `IngestionJob` records to shared `IngestJobResult`.
4. Add focused manager tests.
5. Run manager and ingestion job tests.

## Review Checklist

- The adapter depends only on injected objects and shared contracts.
- It does not import project service or retrieval internals.
- It makes missing status behavior explicit and conservative.
