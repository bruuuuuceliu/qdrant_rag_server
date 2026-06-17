# Retrieval HTTP API Transport

Status: accepted.

## Requirement

Add the first physical retrieval-service network API without changing retrieval
domain logic. The transport must expose the existing retrieval API server
context for search, document delete, and raw-document lookup through a minimal
JSON HTTP interface.

This section is intentionally small. It does not replace the manager public API,
does not add a production broker, and does not rewrite project planning. It only
turns the retrieval-owned transport-neutral API into a separately reachable
service surface.

## Acceptance Criteria

- Retrieval service exposes HTTP handlers for:
  - `POST /search`
  - `POST /documents/delete`
  - `POST /documents/raw`
  - `GET /health`
- Handlers accept JSON payloads shaped like the existing retrieval transport
  commands and return `RetrievalResponseEnvelope` mappings.
- Invalid JSON, non-object JSON, and validation failures return structured
  retrieval error envelopes instead of uncaught exceptions.
- HTTP status mapping is deterministic:
  - successful envelope: `200`
  - validation error envelope: `400`
  - unexpected retrieval error envelope: `500`
  - health response: `200`
- Network server settings are loaded from `./configs/retrieval` and documented in
  env examples.
- Retrieval API boundary modules remain free of manager, project, ingestion,
  generated transport, and gRPC imports.
- Focused unit tests cover the HTTP app behavior without opening a real socket.
- Existing retrieval API server, queue transport, and full test suite remain
  green.

## Structure Design

```text
configs/retrieval/config.py
  RetrievalComponentSettings
  RetrievalHttpSettings
  load_retrieval_http_settings(...)

retrieval_service/server/http.py
  RetrievalHttpApp
  RetrievalHttpRequest
  RetrievalHttpResponse
  create_http_app(...)
  serve_http(...)

retrieval_service/server/app.py
  existing RetrievalApiServerContext remains transport-neutral

tests/test_retrieval_http_server.py
  focused handler tests
```

The HTTP transport lives in `retrieval_service.server` because it is a physical
server adapter. It wraps `RetrievalApiServerContext`; it must not import manager
or project code.

## Class Design

### `RetrievalHttpSettings`

Typed settings for the physical retrieval HTTP server:

- `host`
- `port`
- `read_timeout`

### `RetrievalHttpRequest`

Small testable request object containing:

- `method`
- `path`
- `body`
- `headers`

### `RetrievalHttpResponse`

Small response object containing:

- `status`
- `body`
- `headers`

### `RetrievalHttpApp`

Owns route dispatch from HTTP requests to the retrieval API context. It is
separate from socket serving so tests can call it directly.

### `serve_http(...)`

Starts an asyncio stdlib HTTP server. It is deliberately minimal and exists as a
physical transport adapter over the already-tested app object.

## Implementation Design

1. Add retrieval HTTP config loading in `configs/retrieval/config.py`.
2. Add env example keys:
   - `RETRIEVAL_HTTP_HOST`
   - `RETRIEVAL_HTTP_PORT`
   - `RETRIEVAL_HTTP_READ_TIMEOUT`
3. Implement `retrieval_service/server/http.py` with:
   - route table for the accepted endpoints
   - JSON body parsing and object validation
   - response-envelope status mapping
   - health response
   - minimal asyncio socket server wrapper
4. Export the transport from `retrieval_service/server/__init__.py`.
5. Extend the retrieval API import-boundary guard to cover the HTTP transport.
6. Add focused tests for success, validation, unknown route, and health.
7. Update contracts, roadmap, and progress only after tests pass.

## Review Notes

- This section chooses JSON HTTP because the repository already has JSON-safe
  retrieval envelopes and `httpx` as a dependency.
- gRPC can still be added later as a separate adapter over the same
  `RetrievalApiServerContext`.
- The stdlib server keeps dependencies minimal. Production deployment can place
  a stronger ASGI or gateway layer in front later if needed.
