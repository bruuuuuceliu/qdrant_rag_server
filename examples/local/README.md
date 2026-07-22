# Local Multi-Service Runner

These scripts run the local broker-first multi-service composition for
development. The default topology starts manager, task manager, project domain,
workflow log, ingestion, retrieval, retrieval-index, storage, SQLite, Redis
status, and Qdrant as separate processes when services are enabled.

## Start

```bash
examples/local/run-all.sh --init
```

For a verified first run:

```bash
examples/local/run-all.sh --reset --smoke
```

`--smoke` implies `--init` and returns success only after the manager health,
ingest/status, and strict search client checks pass.
When `RAG_EXAMPLE_EMBEDDING_VERSION` is unset, smoke runs use an embedding
version derived from `RAG_EMBEDDING_PROVIDER` and `RAG_EMBEDDING_DIMENSION` so
Qdrant collections do not collide across local vector-size changes.

Useful options:

```bash
examples/local/run-all.sh --reset --init --grpc-port 50051
examples/local/run-all.sh --init --embedding-provider openrouter
examples/local/run-all.sh --foreground --init
examples/local/run-all.sh --init --no-server
examples/local/run-all.sh --infra-only
examples/local/run-all.sh --no-ui
examples/local/run-all.sh --reset --smoke --no-ui
```

`--no-server` is a setup mode: it resolves local env defaults, writes
`.run/state.env`, and prints the effective local service settings without
starting Qdrant or Python services.

The runner starts:

- manager gRPC server on `RAG_GRPC_PORT`, default `50051`
- task manager, project domain, workflow log, ingestion, retrieval,
  retrieval-index, storage, SQLite, and Redis status worker processes
- Redpanda by default, or Apache Kafka with `--broker kafka`
- Qdrant, when needed and Docker is available

Before reporting startup success, the runner verifies broker topics, Redis
task-status TTL behavior, Qdrant reachability, storage root writes, and SQLite
database allocation through
`python -m deployment.composition.readiness`.

Broker selection:

```bash
examples/local/run-all.sh --infra-only
examples/local/run-all.sh --infra-only --broker kafka
```

Both modes use Docker and expose the broker on `127.0.0.1:9092`.
The local runner applies `qdrant-rag-local.` as the default topic prefix, so it
can reuse an existing Kafka-compatible broker without colliding with another
project's topics. Redis task-status keys similarly default to the
`qdrant-rag-local:task:` prefix.

Local visualization UIs are started by default:

```bash
examples/local/run-all.sh --infra-only
```

- Redpanda Console: `http://127.0.0.1:8088`
- Redis Insight: `http://127.0.0.1:5540`

Use `--no-ui`, `--no-redpanda-console`, or `--no-redis-insight` to skip UI
containers. Redis Insight still requires adding the local Redis database in the
UI with host `127.0.0.1` and port `6379`.

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
matching known service module commands and configured gRPC ports. It also
removes local Docker infra containers by recorded ID or configured name.

## Runtime Files

- Manager log: `.run/logs/manager.log`
- Project planning service log: `.run/logs/project-service.log`
- Ingestion worker log: `.run/logs/ingestion-worker.log`
- Retrieval index worker log: `.run/logs/retrieval-index-worker.log`
- Retrieval helper log: `.run/logs/retrieval-worker.log`
- Qdrant log, when managed by Docker: `.run/logs/qdrant.log`
- PID/state files: `.run/`
- SQLite/object-storage data, including placement registry:
  `.run/data/`

## Notes

- Docker is optional but recommended for Qdrant. If Qdrant is already running at
  `RAG_QDRANT_HOST:RAG_QDRANT_PORT`, `run-all.sh` reuses it.
- The default local embedding provider may download/load a sentence-transformers
  model from Hugging Face. In offline or restricted-network environments, use
  `--embedding-provider deterministic --embedding-model deterministic-hash
  --embedding-dimension 384` for smoke checks, pre-cache `RAG_EMBEDDING_MODEL`,
  or use a remote embedding provider with `RAG_EMBEDDING_API_KEY`.
- `run-all.sh` uses the broker readiness command for dependency checks. If
  startup times out, inspect `.run/logs/*.log`; common blockers are Docker
  socket access, Qdrant not reachable, and embedding model downloads.
- If service startup or `--smoke` fails, the runner stops the processes it
  started and leaves `.run/logs/` available for diagnosis.
- Set `PYTHON_BIN=/path/to/python` when the desired interpreter is not named
  `python` on `PATH`; the runner falls back to `python3` when available.
