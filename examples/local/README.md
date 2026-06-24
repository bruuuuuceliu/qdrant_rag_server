# Local Multi-Service Runner

These scripts run the local broker-first multi-service composition for
development. The default topology starts manager, task manager, project domain,
workflow log, ingestion, retrieval, retrieval-index, storage, SQLite, Redis
status, and Qdrant as separate processes when services are enabled.

## Start

```bash
examples/local/run-all.sh --init
```

Useful options:

```bash
examples/local/run-all.sh --reset --init --grpc-port 50051
examples/local/run-all.sh --init --embedding-provider openrouter
examples/local/run-all.sh --compat-local --reset --init --split-services
examples/local/run-all.sh --compat-local --reset --init --external-retrieval-http
examples/local/run-all.sh --foreground --init
examples/local/run-all.sh --init --no-server
```

`--no-server` is a dry-run/setup mode: it resolves local env defaults, validates
the loaded local config, writes `.run/state.env`, and prints the effective local
service settings without starting Qdrant or Python services.

`--compat-local` enables the older embedded/local queue composition for targeted
migration tests.

`--external-retrieval-http` currently keeps manager project planning local and
only moves retrieval execution to the HTTP service. Do not combine it with
`--external-project-service` or `--split-services` until project config/scope
APIs are extracted.

Broker-first mode starts:

- manager gRPC server on `RAG_GRPC_PORT`, default `50051`
- task manager, project domain, workflow log, ingestion, retrieval,
  retrieval-index, storage, SQLite, and Redis status worker processes
- Qdrant, when needed and Docker is available

Before reporting broker-first startup success, the runner verifies Redpanda
topics, Redis task-status TTL behavior, Qdrant reachability, storage root
writes, and SQLite database allocation through
`python -m deployment.composition.readiness`.

Compatibility split-service mode still supports the older SQLite queue handoff
for migration tests.

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
- `run-all.sh` waits for compatibility gRPC/HTTP ports and uses the broker-first
  readiness command for dependency checks. If startup times out, inspect
  `.run/logs/*.log`; common blockers are Docker socket access, Qdrant not
  reachable, and embedding model downloads.
- Set `PYTHON_BIN=/path/to/python` when the desired interpreter is not named
  `python` on `PATH`; the runner falls back to `python3` when available.
