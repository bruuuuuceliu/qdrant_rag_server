# Manager Ingestion API Status Client

Status: accepted.

## Requirement

Use the ingestion-owned status/control API from manager local composition so
manager status reads go through an ingestion service API boundary instead of
reading the ingestion job repository directly.

This section keeps ingest submission behavior unchanged. In embedded local
mode, manager still submits ingest through the existing local ingestion delegate
or queue path, but `ingest_status(...)` is served by the ingestion API server
context.

## Acceptance Criteria

- Add a manager-facing ingestion client adapter that delegates `ingest(...)` to
  an existing ingestion delegate and maps `ingest_status(...)` through an
  ingestion API context.
- Status success maps ingestion API job payloads to shared `IngestJobResult`.
- Status `not_found` maps to the existing pending fallback behavior for
  compatibility with current manager callers.
- Other ingestion API failures raise clear `RuntimeError` messages.
- Manager embedded-ingestion composition creates an ingestion API app and uses
  the API-backed status client.
- Manager context shutdown closes the ingestion API app once, without
  double-stopping the underlying ingestion app.
- Existing local, queue, HTTP retrieval, and external-ingestion manager modes
  keep passing.
- Focused tests cover adapter mapping, manager composition, and shutdown.

## Structure Design

```text
manager_service/clients.py
  IngestionApiStatusClient

manager_service/server/app.py
  create_api_app(...) from ingestion_service.server
  ManagerAppContext.ingestion_api_app
  embedded ingestion composition uses IngestionApiStatusClient

tests/test_manager_service.py
```

## Class Design

### `IngestionApiStatusClient`

Constructor fields:

- `ingestion`: existing manager-facing ingest delegate
- `api`: ingestion API context exposing `get_status(...)`

Methods:

- `ingest(request)` delegates unchanged.
- `ingest_status(job_id)` calls `api.get_status(...)` and maps envelopes to
  `IngestJobResult`.

## Implementation Design

1. Add `IngestionApiStatusClient` beside other manager client adapters.
2. Keep mapping code local to manager client layer and use only shared
   contracts.
3. Update manager app context to hold the ingestion API app separately from the
   ingestion worker app.
4. In embedded ingestion mode, create `create_ingestion_api_app(...)` after the
   ingestion app is built and wrap the local ingestion delegate with
   `IngestionApiStatusClient`.
5. During shutdown, close the ingestion API app when present; otherwise close
   the ingestion app directly. This avoids stopping the same embedded app twice.
6. Add focused tests and update progress after verification.

## Review Notes

- This is a boundary cleanup, not a physical transport. Remote manager-to-
  ingestion status calls still need an HTTP, queue, or gRPC adapter later.
- The adapter keeps the current pending fallback for missing jobs because public
  manager behavior already relies on it.
- Ingest execution still has compatibility delegation and remains a future
  extraction target.
