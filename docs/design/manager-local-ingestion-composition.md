# Manager Local Ingestion Composition

Section status: implementation accepted for the fourteenth development loop section.

## Requirement Document

`LocalIngestionClient` exists and can resolve ingest status from an ingestion
job repository, but the manager bootstrap still wires its ingestion client
through a project-document compatibility adapter. The ingestion app already
owns the job repository, so the manager composition root should expose that
repository and use `LocalIngestionClient` in local mode.

This section keeps direct ingest execution compatible while moving manager
status reads onto ingestion-owned job state in local composition.

Scope:

- Expose the ingestion job repository from `IngestionAppContext`.
- Wire `manager_service.server.app` to build `LocalIngestionClient` from the
  ingestion app job repository and project client executor.
- Keep retrieval wiring unchanged in this section.

Out of scope:

- Removing compatibility project clients.
- Remote ingestion transport.
- Changing queue behavior.

## Acceptance Criteria

- `IngestionAppContext` exposes the jobs repository.
- Manager local composition uses `LocalIngestionClient` for ingestion in local
  mode.
- Existing manager app tests still pass.
- `progress.md` records the section result.

## Structure Design

Files changed in this section:

```text
ingestion_service/server/
  app.py             expose jobs repository

manager_service/server/
  app.py             local ingestion client composition

tests/
  test_manager_service.py
  test_ingestion_service_server.py

docs/
  design/manager-local-ingestion-composition.md

progress.md
```

## Implementation Design

1. Add `jobs` to `IngestionAppContext`.
2. Store the repository in the ingestion app factory return value.
3. Replace manager local ingestion wiring with `LocalIngestionClient`.
4. Update tests to assert the local ingestion adapter is used in the manager
   app context.
5. Run manager and ingestion server tests.

## Review Checklist

- The manager still uses compatibility project execution for direct ingest.
- Status reads come from ingestion-owned job state when available.
- No new config surface is introduced.
