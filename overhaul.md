# Retrieval Service Structure Overhaul Plan

Date: 2026-06-08

Goal: keep the original project structure, but make configuration explicit, rename the main package from `rag_server` to `retrieval_service`, and move server startup/transport code into a top-level `./server/` folder.

This is a planning document only. It should guide the next code changes.

## 1. Direction

Do not redesign the whole repository into many new top-level packages.

The current structure is mostly understandable:

```text
core/
adapters/
gateway/
engine/
services/
storage/
config/
grpc/
health/
versioning/
```

The better overhaul is smaller:

- add a top-level `configs/` folder for all environment and settings loading
- rename `rag_server/` to `retrieval_service/`
- move actual server code into top-level `server/`
- keep core retrieval functionality in the familiar original folders
- keep examples, docs, deployment, and tests clearly separated

## 2. Required Config Rule

All environment variables, private keys, and deployment-specific settings should flow through:

```text
key / value -> selected .env file -> configs/config.py -> typed settings -> code
```

Runtime code should not call `os.getenv()` directly. Code should receive typed settings from `configs/config.py`.

Real `.env` files should not be committed. Commit `*.env.example` templates only.

## 3. Proposed Layout

```text
qdrant_retrieval_service/
  configs/
    config.py
    local.env.example
    testing.env.example
    production.env.example
    embeddings/
      config.py
      local.env.example
      openrouter.env.example
    qdrant/
      config.py
      local.env.example
      cloud.env.example
    generation/
      config.py
      disabled.env.example
      openrouter.env.example
    storage/
      config.py
      memory.env.example
      filesystem.env.example
      s3.env.example
    project/
      __init__.py
      repository.py

  retrieval_service/
    __init__.py
    core/
      __init__.py
      models.py
    adapters/
      __init__.py
      base.py
      website.py
    gateway/
      __init__.py
      handler.py
    engine/
      __init__.py
      engine.py
    services/
      __init__.py
      cache.py
      embedding.py
      generation.py
      reranker.py
      vector_store.py
    storage/
      __init__.py
      base.py
      memory.py
      filesystem.py
      s3.py
    health/
      __init__.py
      health.py
    versioning/
      __init__.py
      manager.py

  server/
    __init__.py
    app.py
    bootstrap.py
    grpc/
      __init__.py
      server.py
      generated/
        __init__.py
        retrieval_service_pb2.py
        retrieval_service_pb2_grpc.py
    proto/
      retrieval_service.proto

  deployment/
    local/
      start.sh
    docker/
      Dockerfile
      docker-compose.yml
    systemd/
      qdrant-retrieval-service.service.example

  examples/
    README.md
    seed_project.py
    ingest_search.py
    grpc_client.py

  docs/
    README.md
    overview.md
    architecture.md
    configuration.md
    workflows.md
    api.md
    data-model.md
    development.md
    extension-guide.md
    design/

  tests/
    test_phase1_core.py
    test_phase2_gateway.py
    test_phase3_engine.py
    ...

  README.md
  pyproject.toml
  overhaul.md
```

## 4. Folder Responsibilities

### `configs/`

Owns application settings, environment loading, and project configuration persistence.

Responsibilities:

- load selected `.env` files
- merge base/profile/component settings
- validate required fields
- expose typed settings dataclasses
- keep secrets out of runtime code
- persist project configuration records under `configs/project/`

Example public API:

```python
from configs.config import load_settings

settings = load_settings(profile="local")
```

Supported variants:

```text
configs/local.env and configs/config.py
configs/testing.env and configs/config.py
configs/production.env and configs/config.py
configs/embeddings/local.env and configs/embeddings/config.py
configs/embeddings/openrouter.env and configs/embeddings/config.py
configs/qdrant/local.env and configs/qdrant/config.py
configs/qdrant/cloud.env and configs/qdrant/config.py
configs/generation/openrouter.env and configs/generation/config.py
configs/storage/s3.env and configs/storage/config.py
```

Project configuration repository path:

```text
configs/project/repository.py
```

### `retrieval_service/core/`

Shared domain models:

- project config model
- query scope
- retrieval filter
- document
- chunk
- chunk payload
- ingest job status

### `retrieval_service/adapters/`

Project/data adapters.

Keep the existing adapter boundary. Adapters parse source input, build chunks, build payloads, and own project/data-specific behavior.

### `retrieval_service/gateway/`

Request validation and scope enforcement.

The gateway should normalize request intent and reject unsafe raw filters. It should not own Qdrant-specific implementation details.

### `retrieval_service/engine/`

Retrieval and ingestion orchestration.

The engine should coordinate adapters, embeddings, vector store, cache, storage, jobs, and optional reranking/generation. It should not parse env files or own transport details.

### `retrieval_service/services/`

Runtime service implementations:

- embeddings
- vector store
- reranker
- cache
- generation client

Keep the original `services/` folder. It is a useful bucket for replaceable implementations. Do not split it into a top-level package.

### `retrieval_service/storage/`

Raw object storage implementations:

- memory
- filesystem
- S3-compatible

Keep this as its own folder because raw content backup is a distinct concept from vector retrieval services.

### `retrieval_service/health/`

Health checks and metrics.

Keep it lightweight and optional.

### `retrieval_service/versioning/`

Embedding collection version metadata and migration helpers.

### `server/`

All process startup and transport code.

Responsibilities:

- app entrypoint
- bootstrap/wiring
- gRPC server implementation
- generated protobuf code
- proto definition
- server lifecycle

This folder should be the only place that knows how the service process starts.

Recommended entrypoint:

```bash
python -m server.app
```

### `deployment/`

Deployment and startup material:

- local startup script
- Docker files
- systemd examples

### `examples/`

Runnable examples only:

- seed project config
- ingest
- search
- check job status
- gRPC client usage

### `docs/`

Durable documentation.

Root planning notes should eventually move under `docs/design/` or be removed after they become stale.

## 5. Existing File Mapping

```text
.env.example                         -> configs/local.env.example

rag_server/                          -> retrieval_service/

rag_server/app.py                    -> server/app.py
rag_server/grpc/server.py            -> server/grpc/server.py
rag_server/grpc/rag_service_pb2.py   -> server/grpc/generated/retrieval_service_pb2.py
rag_server/grpc/rag_service_pb2_grpc.py -> server/grpc/generated/retrieval_service_pb2_grpc.py
proto/rag_service.proto              -> server/proto/retrieval_service.proto

rag_server/core/                     -> retrieval_service/core/
rag_server/adapters/                 -> retrieval_service/adapters/
rag_server/gateway/                  -> retrieval_service/gateway/
rag_server/engine/                   -> retrieval_service/engine/
rag_server/services/                 -> retrieval_service/services/
rag_server/storage/                  -> retrieval_service/storage/
rag_server/config/                   -> configs/project/
rag_server/health/                   -> retrieval_service/health/
rag_server/versioning/               -> retrieval_service/versioning/

examples/local/start.sh              -> deployment/local/start.sh
```

## 6. Config Loading Design

Suggested typed settings:

```python
@dataclass(frozen=True, slots=True)
class AppSettings:
    runtime: RuntimeSettings
    server: ServerSettings
    qdrant: QdrantSettings
    embeddings: EmbeddingSettings
    generation: GenerationSettings
    storage: StorageSettings
    cache: CacheSettings
    project_config: ProjectConfigSettings
    limits: LimitSettings
```

Suggested loader:

```python
def load_settings(
    *,
    profile: str = "local",
    env_file: str | Path | None = None,
    component_env_files: Sequence[str | Path] = (),
) -> AppSettings:
    ...
```

Example flows:

```text
local dev:
  configs/local.env
  configs/embeddings/local.env
  configs/qdrant/local.env

remote embeddings:
  configs/local.env
  configs/embeddings/openrouter.env

production:
  configs/production.env
  configs/qdrant/cloud.env
  configs/storage/s3.env
```

## 7. Secret Handling Rules

Add to `.gitignore`:

```text
configs/**/*.env
!configs/**/*.env.example
```

Rules:

- never commit real `.env` files
- never read private keys outside `configs/config.py`
- never store provider keys in SQLite project config
- never store provider keys in Qdrant payloads
- never include provider keys in cache keys or cache values
- never log provider keys

## 8. Import Rules

Allowed:

```text
server/ -> configs/
server/ -> retrieval_service/*
retrieval_service/engine/ -> retrieval_service/services/
retrieval_service/engine/ -> retrieval_service/storage/
retrieval_service/gateway/ -> retrieval_service/adapters/
```

Avoid:

```text
retrieval_service/core/ -> retrieval_service/services/
retrieval_service/core/ -> configs/
retrieval_service/adapters/ -> configs/
retrieval_service/services/ -> server/
```

The core model layer should stay dependency-light.

## 9. Migration Plan

### Phase 1: Add `configs/`

Tasks:

- create `configs/`
- move `.env.example` to `configs/local.env.example`
- add `configs/config.py`
- add typed settings dataclasses
- update current app startup to load settings through `configs/config.py`
- add `.gitignore` rules for real `.env` files

Acceptance criteria:

- config flow is `key -> .env -> configs/config.py -> code`
- no runtime module except `configs/config.py` reads env vars directly

### Phase 2: Rename Package

Tasks:

- rename `rag_server/` to `retrieval_service/`
- update imports
- update `pyproject.toml` package discovery
- optionally keep a temporary `rag_server/` compatibility shim if existing callers need it

Acceptance criteria:

- tests import `retrieval_service`
- the project identity is retrieval-first, not generation-first

### Phase 3: Move Server Code

Tasks:

- create top-level `server/`
- move app bootstrap into `server/app.py`
- split wiring helpers into `server/bootstrap.py`
- move gRPC code under `server/grpc/`
- move generated protobuf files under `server/grpc/generated/`
- move proto file under `server/proto/`

Acceptance criteria:

- `python -m server.app` starts the service
- transport/server code is not mixed with core retrieval code
- generated code is isolated

### Phase 4: Deployment And Examples

Tasks:

- move `examples/local/start.sh` to `deployment/local/start.sh`
- update startup script to use `configs/`
- keep runnable ingest/search examples under `examples/`
- update docs to reference the new entrypoint

Acceptance criteria:

- deployment scripts are separate from examples
- examples stay small and runnable

### Phase 5: Documentation Cleanup

Tasks:

- update `README.md`
- update `docs/architecture.md`
- update `docs/configuration.md`
- update `docs/development.md`
- move historical planning notes into `docs/design/` if they remain useful

Acceptance criteria:

- docs match the actual file layout
- root directory is easier to scan

## 10. Recommended First Change

Start with config. Do not rename the package first.

First concrete step:

```text
create configs/config.py
create configs/local.env.example
update current app startup to use load_settings()
```

Then rename `rag_server/` to `retrieval_service/`, and only after that move server-specific code into top-level `server/`.
