# Retrieval Transport Contracts

Section status: implementation accepted for the next development loop section.

## Requirement Document

The retrieval facade owns search, delete, and raw-document operations. The
broker-first split needs transport-neutral contracts so retrieval helper
workers can carry the same operations through Redpanda command/result topics
without importing manager or project internals.

Scope:

- Add serializable request and response envelopes for retrieval search,
  document delete, and raw-document lookup.
- Keep conversion into current `RetrievalService` request objects close to the
  retrieval facade.
- Preserve the existing local facade dataclasses and service behavior.
- Validate required routing fields before execution.

Out of scope:

- gRPC, HTTP, or protobuf generation.
- Manager remote retrieval clients.
- Project gateway planning transport.
- Changing retrieval ranking, filtering, cache, or storage behavior.

## Acceptance Criteria

- Search, delete, and raw-document request contracts can be built from mapping
  payloads and serialized back to mappings.
- Search and delete contracts convert to the existing retrieval facade request
  dataclasses.
- Response envelopes serialize successful results and structured errors without
  transport-specific dependencies.
- Required retrieval fields are validated with clear `ValueError` messages.
- Tests cover contract parsing, conversion, serialization, and validation.
- `docs/contracts.md`, `docs/design/section-design-index.md`, and
  `progress.md` record the accepted section.

## Structure Design

Files changed in this section:

```text
retrieval_service/retrieval/
  contracts.py       transport-neutral retrieval API contracts
  __init__.py        public exports

tests/
  test_retrieval_transport_contracts.py

docs/
  contracts.md
  design/retrieval-transport-contracts.md
  design/section-design-index.md

progress.md
```

## Class Design

### `RetrievalApiError`

Fields:

- `code`
- `message`
- `retryable`

Methods:

- `to_mapping()`

### `RetrievalResponseEnvelope`

Fields:

- `request_id`
- `ok`
- `result`
- `error`

Methods:

- `success(...)`
- `failure(...)`
- `to_mapping()`

### `RetrievalSearchCommand`

Fields mirror the retrieval facade search request and add boundary metadata:

- `request_id`
- `response_topic`
- `project_id`
- `user_id`
- `query_text`
- `collection_name`
- `retrieval_config`
- `retrieval_filter`
- `cache_key`

Methods:

- `from_payload(...)`
- `request_payload()`
- `validate()`
- `to_service_request()`

### `RetrievalDeleteDocumentCommand`

Fields:

- `request_id`
- `response_topic`
- `project_id`
- `user_id`
- `kb_id`
- `doc_id`
- `collection_name`

Methods:

- `from_payload(...)`
- `request_payload()`
- `validate()`
- `to_service_request()`

### `RetrievalRawDocumentCommand`

Fields:

- `request_id`
- `response_topic`
- `project_id`
- `user_id`
- `doc_id`

Methods:

- `from_payload(...)`
- `request_payload()`
- `validate()`
- `to_service_request()`

## Implementation Design

1. Add a `contracts.py` module inside `retrieval_service.retrieval`.
2. Parse payloads that may be direct request mappings or envelopes containing
   `request_id`, `response_topic`, and nested `request`.
3. Validate required fields in command objects before conversion to facade
   requests.
4. Return plain dictionaries from serialization helpers so broker workers can
   encode them as Redpanda payloads without transport-specific dependencies.
5. Export the new contracts from `retrieval_service.retrieval`.
6. Add focused unit tests and run the retrieval/docs focused suite.

## Review Checklist

- Contracts do not import manager or project service internals.
- No generated gRPC files are edited.
- Existing retrieval service request dataclasses remain backward compatible.
- Payload parsing stays explicit and avoids ad hoc mutation of caller mappings.
