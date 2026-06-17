# Retrieval API Queue Transport

Section status: implementation accepted for the next development loop section.

## Requirement Document

The retrieval service now has a server context with payload-based search,
delete, and raw-document methods. It still lacks a concrete transport that can
run out-of-process without editing the compatibility gRPC proto. Add a local
queue request/response transport around the retrieval API server context using
the existing `shared.queue` contract.

Scope:

- Add a retrieval API queue consumer for `retrieval.api.requests`.
- Add a retrieval API queue client that publishes request envelopes and waits on
  per-request response topics.
- Support operations `search`, `delete_document`, and `get_raw_document`.
- Preserve response-envelope mappings from `RetrievalApiServerContext`.
- Keep queue transport modules retrieval-owned.

Out of scope:

- Production broker retry/claim/dead-letter behavior.
- gRPC/HTTP network transport.
- Manager bootstrap wiring to remote retrieval queue mode.
- Raw-document public manager routes.

## Acceptance Criteria

- The queue consumer consumes retrieval API request messages and publishes
  response-envelope mappings to the requested response topic.
- The queue client publishes search/delete/raw-document requests and returns the
  response-envelope mapping.
- Unknown operations return non-retryable `validation_error` envelopes.
- Client timeouts raise a clear `RetrievalApiQueueTimeoutError`.
- Tests cover success, unknown operation, and timeout behavior.
- Docs and `progress.md` record the section result.

## Structure Design

Files changed in this section:

```text
retrieval_service/server/
  queue.py           retrieval API queue consumer/client
  __init__.py        public exports

tests/
  test_retrieval_api_queue.py

docs/
  design/retrieval-api-queue-transport.md
  design/section-design-index.md

progress.md
```

## Class Design

### `RetrievalApiQueueConsumer`

Constructor:

- `queue`
- `api`
- `topic`

Methods:

- `start()`
- `stop()`
- `topic`

### `RetrievalApiQueueClient`

Constructor:

- `queue`
- `topic`
- `response_timeout`

Methods:

- `search(payload)`
- `delete_document(payload)`
- `get_raw_document(payload)`

### `RetrievalApiQueueTimeoutError`

Raised when a response does not arrive before the configured timeout.

## Implementation Design

1. Define a request payload shape:

   ```python
   {
       "request_id": "...",
       "response_topic": "retrieval.api.responses.<request_id>",
       "operation": "search",
       "request": {...},
   }
   ```

2. Consumer dispatches operations to the retrieval API server context.
3. Consumer publishes the returned response envelope to `response_topic`.
4. Unknown operations publish `validation_error` envelopes.
5. Client publishes one request, waits on the response topic, acknowledges the
   consumed response when supported, and returns its payload.
6. Add focused tests using `LocalQueueBroker`.

## Review Checklist

- No generated gRPC files are edited.
- Queue transport imports only retrieval-owned API/server modules and shared
  queue contracts.
- Request/response payloads stay plain mappings.
- Client timeout handling does not leave successful responses unacknowledged.
