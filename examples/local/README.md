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
examples/local/run-all.sh --reset --init --external-retrieval-http
examples/local/run-all.sh --foreground --init
examples/local/run-all.sh --init --no-server
```

`--no-server` is a dry-run/setup mode: it resolves local env defaults, validates
the loaded local config, writes `.run/state.env`, and prints the effective local
service settings without starting Qdrant or Python services.

`--external-retrieval-http` currently keeps manager project planning local and
only moves retrieval execution to the HTTP service. Do not combine it with
`--external-project-service` or `--split-services` until project config/scope
APIs are extracted.

Split-service mode starts:

- manager gRPC server on `RAG_GRPC_PORT`, default `50051`
- project/RAG gRPC server on `RAG_PROJECT_GRPC_PORT`, default `50052`
- ingestion worker server connected through the shared queue
- retrieval index worker connected through the shared queue
- retrieval HTTP server when `--external-retrieval-http` is set
- Qdrant, when needed and Docker is available

In split-service mode, queued ingestion publishes prepared chunks to the
retrieval index worker and waits for the index response before marking the
ingestion job completed. The no-index compatibility path is still available
when the retrieval index worker is not enabled.

Copy `configs/local.env.example` to `configs/local.env` to keep local overrides
out of command arguments. `run-all.sh` reads `configs/local.env` by default;
use `--env-file PATH` only for an alternate config file under `configs/`.

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
- Retrieval index worker log: `.run/logs/retrieval-index-worker.log`
- Retrieval HTTP server log: `.run/logs/retrieval-http.log`
- Qdrant log, when managed by Docker: `.run/logs/qdrant.log`
- PID/state files: `.run/`
- SQLite/object-storage data, including placement registry:
  `examples/local/.data/`

## Notes

- Docker is optional but recommended for Qdrant. If Qdrant is already running at
  `RAG_QDRANT_HOST:RAG_QDRANT_PORT`, `run-all.sh` reuses it.
- The default local embedding provider may download/load a sentence-transformers
  model from Hugging Face. In offline or restricted-network environments, either
  pre-cache `RAG_EMBEDDING_MODEL` locally or use a remote embedding provider with
  `RAG_EMBEDDING_API_KEY`.
- `run-all.sh` waits for gRPC/HTTP ports before reporting services as started.
  If startup times out, inspect `.run/logs/*.log`; common blockers are Docker
  socket access, Qdrant not reachable, and embedding model downloads.
- Set `PYTHON_BIN=/path/to/python` when the desired interpreter is not named
  `python` on `PATH`; the runner falls back to `python3` when available.
