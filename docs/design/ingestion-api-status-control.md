# Ingestion API Status And Control

Status: accepted.

## Requirement

Add an ingestion-owned API layer for job status and worker control/health that
can be wrapped by future HTTP, gRPC, or queue transports without exposing
manager, project, retrieval, or parser internals.

This section does not replace queued ingest submission or compatibility ingest
execution. It provides the first independent ingestion service API surface over
the existing `IngestionAppContext` and job repository.

## Acceptance Criteria

- Ingestion API contracts live under `ingestion_service.server` or
  ingestion-owned modules, not `shared`.
- A status command parses direct payloads and request-envelope payloads.
- Status returns an ingestion-owned response envelope with structured success,
  not-found, validation, and internal-error results.
- Health/control returns worker enabled state, request topic, and whether job
  storage is configured.
- The API handler delegates only to an ingestion app context and job repository.
- The API server context exposes `get_status(...)` and `health(...)` payload
  methods for future transports.
- Ingestion API modules do not import manager, project, retrieval, generated
  transport modules, or `grpc`.
- Focused tests cover parsing, status success/not found, validation failures,
  health/control payloads, server context dispatch, and import boundaries.

## Structure Design

```text
ingestion_service/server/contracts.py
  IngestionStatusCommand
  IngestionApiError
  IngestionResponseEnvelope
  job_to_mapping(...)

ingestion_service/server/handler.py
  IngestionApiHandler

ingestion_service/server/api.py
  IngestionApiServerContext
  create_api_app(...)

tests/test_ingestion_api_contracts.py
tests/test_ingestion_api_handler.py
tests/test_ingestion_api_server.py
tests/test_ingestion_api_import_boundaries.py
```

## Class Design

### `IngestionStatusCommand`

Fields:

- `request_id`
- `job_id`

Class method:

- `from_payload(payload, fallback_request_id)` accepts either direct payloads or
  `{request_id, request: {...}}` envelopes.

### `IngestionResponseEnvelope`

Fields:

- `request_id`
- `ok`
- `result`
- `error`

Methods:

- `success(...)`
- `failure(...)`
- `to_mapping()`

### `IngestionApiHandler`

Methods:

- `get_status(payload, fallback_request_id="ingestion-status")`
- `health(payload=None, fallback_request_id="ingestion-health")`

### `IngestionApiServerContext`

Methods:

- `get_status(...)`
- `health(...)`
- `shutdown()` delegates to the ingestion app context.

## Implementation Design

1. Add ingestion-owned contracts for status commands and response envelopes.
2. Add mapping from `IngestionJob` to transport-safe dictionaries.
3. Add an API handler that reads status from `IngestionAppContext.jobs` and
   reports clear envelopes for unavailable job storage or missing jobs.
4. Add an API server context that wraps an `IngestionAppContext` and handler.
5. Export the API context and contracts from `ingestion_service.server`.
6. Add AST import-boundary tests for the API contracts, handler, and server
   context.
7. Update roadmap and progress after focused and full verification.

## Review Notes

- This is intentionally transport-neutral; HTTP or queue adapters should wrap
  the server context in later sections.
- Submit/cancel/pause controls are out of scope until worker execution state is
  owned end to end by ingestion service.
- The API reports worker configuration and health, but it does not claim
  production liveness semantics.
