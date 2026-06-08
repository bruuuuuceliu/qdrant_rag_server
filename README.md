# qdrant_retrieval_service

Async project-scoped information retrieval service built around Qdrant, project/data adapters, gRPC, optional reranking, object storage backup, and simple caching.

Despite the repository name, the intended core is broader than RAG: ingest data, index it, retrieve it, filter it, delete it, and report job status. LLM answer generation is optional and should not be required for retrieval-only deployments.

## Current Status

This repository is a **prototype / core scaffold**. It has the right architectural pieces, but it should not be treated as production-ready yet.

Implemented scaffold:

- core project/user/KB/document/chunk models
- default KB behavior when callers do not need KB separation
- project adapter interface
- website adapter prototype
- SQLite project config repository
- gateway request validation and server-built retrieval filters
- Qdrant vector store wrapper
- async search pipeline with optional reranking
- async ingest workers
- in-memory ingest status
- memory/filesystem/S3-compatible object storage abstractions
- Tier-1 retrieval cache and Tier-2 SQLite response cache
- gRPC service boundary
- health and basic metrics
- embedding collection version manager

Main known gaps:

- SQLite and filesystem paths are still fake-async in places.
- Ingest jobs are not durable.
- Ingest queue is unbounded.
- Raw content is hidden in `metadata["raw_text"]` instead of being a first-class input.
- Website adapter config is hard-coded.
- Retrieval is still vector-first; BM25/hybrid retrievers need a shared retriever framework.
- Data types need a registry so each type can own schema, parsing, filters, and retrieval defaults.
- Generation is experimental and should not define the core RAG path.

## Minimal Target

The next stable milestone should be:

```text
Minimal safe information retrieval core:
project/user-scoped ingest, search, delete, cache invalidation, and raw backup.
```

Keep the server focused on retrieval and ingestion first. Add larger platform features later.

Design guardrails:

- Minimal: only essential ingest/search/delete/status/raw-backup behavior belongs in the core.
- Extensible: transports, status repositories, adapters, retrievers, rerankers, storage, embeddings, and generation clients should be replaceable.
- Data-type aware: different data types may have different schemas, filters, chunking, and retrieval methods.
- Retrieval-first: vector search is the current implementation, but BM25, hybrid, and metadata retrieval should fit behind the same retriever interface.
- Configurable: execution should come from project/request configuration, including user-provided LLM provider keys when generation is enabled.

## Architecture

```text
gRPC / caller
  -> gateway validation
  -> project adapter resolution
  -> server-built retrieval filters
  -> RagEngine
       -> retriever coordinator
       -> vector retriever / future BM25 retriever / future hybrid retriever
       -> optional reranker
       -> caches
       -> object storage for raw-document backup during ingest
```

Query-time retrieval reads chunk text from Qdrant payloads. Remote object storage is for raw document durability and rebuilds, not online query serving.

## Project Layout

```text
configs/                    application and environment config loading
retrieval_service/core/            base models
retrieval_service/adapters/        project adapter contract and website adapter
retrieval_service/config/          SQLite project config repository
retrieval_service/gateway/         request validation and scope enforcement
retrieval_service/engine/          search, generation, and ingestion orchestration
retrieval_service/services/        Qdrant, embedding, reranker, cache, generation
retrieval_service/storage/         object storage abstractions
retrieval_service/health/          health checks and metrics
retrieval_service/versioning/      embedding collection version manager
server/                     app entrypoint, gRPC server, generated stubs, proto
deployment/                 startup and deployment scripts
examples/                   runnable usage examples
tests/                      phase-based unit tests
```

## Development Environment

Use the `evo` conda environment:

```bash
source /home/bruce/miniconda3/etc/profile.d/conda.sh
conda activate evo
```

Install project dependencies when needed:

```bash
python -m pip install -e ".[dev]"
```

Run tests:

```bash
python -m pytest -q
```

If tests fail at collection with `ModuleNotFoundError: qdrant_client`, install the project dependencies first.

## Documentation

Read these first:

- [Documentation index](docs/README.md)
- [Overview](docs/overview.md)
- [Architecture](docs/architecture.md)
- [Data model](docs/data-model.md)
- [Workflows](docs/workflows.md)
- [API](docs/api.md)
- [Configuration](docs/configuration.md)
- [Extension guide](docs/extension-guide.md)
- [Development](docs/development.md)
- [Examples](examples/README.md)

Planning and review notes:

- [details.md](details.md) for the current implementation plan
- [progress.md](progress.md) for current implementation status
- [report.md](report.md) and [update.md](update.md) for source-reviewed critique and historical planning
