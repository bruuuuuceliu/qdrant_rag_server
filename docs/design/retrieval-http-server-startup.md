# Retrieval HTTP Server Startup

Status: accepted.

## Requirement

Add a standalone retrieval HTTP server entry point that builds retrieval-owned
runtime dependencies and serves the existing retrieval HTTP API transport.

The manager already supports `MANAGER_RETRIEVAL_CLIENT_MODE=http`, but the repo
does not yet provide a runnable retrieval HTTP service process. This section
makes the retrieval HTTP transport usable in local split-service development
without involving the project/RAG compatibility server.

## Acceptance Criteria

- `python -m retrieval_service.server.worker` starts a retrieval HTTP server.
- Server settings load from `configs/retrieval` and `AppSettings`.
- The bootstrap builds retrieval-owned dependencies only: embedding provider,
  Qdrant store, dense/BM25 retrievers, sparse encoder, NER extractor, caches,
  metrics, and object storage.
- The bootstrap wraps the retrieval service with the existing retrieval API
  server context and HTTP app.
- Shutdown closes the HTTP server, API context, embedding provider, BM25 index,
  Qdrant store, and optional NER resources cleanly.
- The worker module does not import manager, project, ingestion, generated
  transport modules, or `grpc`.
- Tests use injected fakes so no Qdrant server, embedding model, or network port
  is required.
- Focused tests cover composition, shutdown, settings propagation, and import
  boundaries.

## Structure Design

```text
retrieval_service/server/worker.py
  RetrievalHttpServerContext
  create_worker_server(...)
  serve_forever(...)
  main()

examples/local/run-all.sh
  future section can start this worker for HTTP retrieval mode

tests/test_retrieval_http_worker.py
tests/test_retrieval_api_import_boundaries.py
```

## Class Design

### `RetrievalHttpServerContext`

Fields:

- `api_app`
- `http_app`
- `http_server`
- `settings`
- owned retrieval dependency references

Method:

- `shutdown()` closes the HTTP server first, then the retrieval API context and
  owned dependencies.

## Implementation Design

1. Add `retrieval_service.server.worker` with injectable optional dependencies
   for tests.
2. Build default dependencies from `AppSettings` only when not injected.
3. Use `RetrievalService`, `ProjectRetrieverFactory`, `QdrantVectorRetriever`,
   `BM25Retriever`, `QdrantSparseBM25Index`, `FastEmbedSparseTextEncoder`, and
   existing cache/storage components for production-local composition.
4. Create the retrieval API app with `create_app(...)`, then the HTTP app with
   `create_http_app(...)`, then bind the stdlib HTTP server with
   `serve_http(...)` when enabled.
5. Add tests that inject fake retrieval service and fake HTTP server to verify
   lifecycle without opening sockets.
6. Update docs and progress after focused and full verification.

## Review Notes

- This is a process bootstrap, not a new retrieval API contract.
- Manager-to-retrieval HTTP mode still requires project planning in manager
  local composition until project config/scope APIs are extracted.
- Live HTTP smoke with real Qdrant remains separate because it depends on local
  infrastructure availability.
