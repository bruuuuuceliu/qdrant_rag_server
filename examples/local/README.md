# Local Multi-Service Runner

These scripts run the current local multi-service composition for development.
The manager process owns the public gRPC server. By default it composes the
project service and ingestion consumer in-process for a small local setup.
For service-boundary development, `--split-services` starts project/RAG and
ingestion worker processes separately. Qdrant runs as a separate local server
when Docker is available.

## Start

```bash
examples/local/run-all.sh --init
```

Useful options:

```bash
examples/local/run-all.sh --reset --init --grpc-port 50051
examples/local/run-all.sh --init --embedding-provider openrouter
examples/local/run-all.sh --reset --init --external-ingestion
examples/local/run-all.sh --reset --init --split-services
examples/local/run-all.sh --foreground --init
examples/local/run-all.sh --init --no-server
```

Split-service mode starts:

- manager gRPC server on `RAG_GRPC_PORT`, default `50051`
- project/RAG gRPC server on `RAG_PROJECT_GRPC_PORT`, default `50052`
- ingestion worker server connected through the shared queue
- Qdrant, when needed and Docker is available

Copy `examples/local/local.env.example` to `examples/local/local.env` to keep
local overrides out of command arguments.

## Stop

```bash
examples/local/stop-all.sh
```

Cleanup options:

```bash
examples/local/stop-all.sh --clean
examples/local/stop-all.sh --clean --clean-data
```

`stop-all.sh` first uses PID/container state from `.run`, then falls back to
matching known service module commands and configured gRPC ports. It removes the
local Qdrant container by name unless `--no-docker` is set.

## Runtime Files

- Manager log: `.run/logs/manager.log`
- Project/RAG service log: `.run/logs/project-service.log`
- Ingestion worker log: `.run/logs/ingestion-worker.log`
- Qdrant log, when managed by Docker: `.run/logs/qdrant.log`
- PID/state files: `.run/`
- SQLite/object-storage data: `examples/local/.data/`

## Notes

- Docker is optional but recommended for Qdrant. If Qdrant is already running at
  `RAG_QDRANT_HOST:RAG_QDRANT_PORT`, `run-all.sh` reuses it.
- The default local embedding provider may download/load a sentence-transformers
  model. For remote embeddings, set `RAG_EMBEDDING_API_KEY`.
