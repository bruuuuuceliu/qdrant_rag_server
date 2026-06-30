# Retrieval API Handler

Section status: implementation accepted for the next development loop section.

## Requirement Document

The retrieval service has transport-neutral command DTOs, and the Redpanda
helper worker needs a retrieval-owned entry point that accepts plain payload
mappings, calls the retrieval app context, and returns response envelopes. The
search path also needs retrieval-owned filter normalization so payloads do not
depend on project-service filter classes.

Scope:

- Add a retrieval-owned filter spec for transport payloads.
- Normalize search command `retrieval_filter` mappings into the filter spec.
- Add a `RetrievalApiHandler` that handles search, delete, and raw-document
  payloads through `RetrievalAppContext`-compatible methods.
- Return `RetrievalResponseEnvelope` mappings for success and validation errors.

Out of scope:

- Network server startup.
- Network or protobuf adapters outside the Redpanda helper flow.
- Manager remote retrieval client wiring.
- Retry, auth, or rate limiting.

## Acceptance Criteria

- Search payloads with mapping filters convert into retrieval-owned filter
  specs before calling the app context.
- Search, delete, and raw-document handler methods return successful response
  envelope mappings.
- Validation errors return structured `validation_error` envelopes instead of
  raising through the handler.
- Unexpected application errors return structured `internal_error` envelopes.
- Tests cover success and error paths without importing project-service models.
- Docs and `progress.md` record the section result.

## Structure Design

Files changed in this section:

```text
retrieval_service/retrieval/
  contracts.py       filter spec normalization
  handler.py         transport-neutral API handler
  __init__.py        public exports

tests/
  test_retrieval_api_handler.py
  test_retrieval_transport_contracts.py

docs/
  design/retrieval-api-handler.md
  design/section-design-index.md

progress.md
```

## Class Design

### `RetrievalFilterSpec`

Fields:

- `project_id`
- `allowed_user_ids`
- `kb_ids`
- `doc_ids`

Methods:

- `from_mapping(...)`
- `to_mapping()`

### `RetrievalApiHandler`

Fields:

- `app`

Methods:

- `handle_search(payload, fallback_request_id)`
- `handle_delete_document(payload, fallback_request_id)`
- `handle_raw_document(payload, fallback_request_id)`

## Implementation Design

1. Add `RetrievalFilterSpec` to retrieval contracts.
2. Normalize mapping `retrieval_filter` values during search-command parsing.
3. Add a handler module that parses commands, converts them to facade requests,
   calls the app context, and wraps results in response envelopes.
4. Treat command validation errors as non-retryable validation failures.
5. Treat unexpected app errors as retryable internal failures.
6. Export the handler and add focused tests.

## Review Checklist

- Handler imports only retrieval-owned modules.
- Handler returns mappings and remains transport-agnostic.
- Mapping filters do not require project-service classes.
- Existing local object-filter compatibility remains intact.
