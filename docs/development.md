# Development

## Environment

Use the `evo` conda environment:

```bash
source /home/bruce/miniconda3/etc/profile.d/conda.sh
conda activate evo
```

Install the project in editable mode:

```bash
python -m pip install -e ".[dev]"
```

Run tests:

```bash
python -m pytest -q
```

In this workspace, the known-good test command is:

```bash
/home/bruce/miniconda3/envs/evo/bin/python -m pytest -q
```

## Running The Server

The local app entrypoint is:

```bash
python -m server.app
```

Configure it through environment variables. See [Configuration](configuration.md).

Generation is disabled by default:

```text
RAG_GENERATION_ENABLED=false
```

## Test Structure

Tests are phase-based:

```text
tests/test_phase1_core.py
tests/test_phase2_gateway.py
tests/test_phase3_engine.py
tests/test_phase4_reranker.py
tests/test_phase5_ingestion.py
tests/test_phase6_website_adapter.py
tests/test_phase7_cache.py
tests/test_phase8_generation.py
tests/test_phase9_versioning.py
tests/test_phase10_health.py
tests/test_phase11_e2e.py
```

The suite is mostly unit and mocked integration coverage. It is useful as a scaffold, but production confidence will need stronger integration tests around Qdrant, durable jobs, object storage, and concurrency.

## Current Implementation Notes

Implemented recently:

- default KB normalization
- scoped Qdrant point IDs
- scoped Qdrant document delete
- embedding provider object wiring
- app health and metrics wiring
- opt-in generation client
- generation-unavailable behavior
- search `elapsed_ms`
- in-memory ingest error/doc/timestamp fields

Still important:

- SQLite operations are not async-safe yet.
- Filesystem storage operations are not async-safe yet.
- Ingest jobs are not durable.
- Ingest queue is unbounded.
- Raw content is not typed.
- Retrieval framework for BM25/hybrid does not exist yet.
- Data-type registry does not exist yet.
- Website adapter config is hard-coded.

## Next Implementation Order

1. Make SQLite and filesystem persistence async-safe.
2. Add bounded durable ingest job repository.
3. Expose typed fields through gRPC/gateway.
4. Extend retrieval filters for data type, visibility, and versions.
5. Add retrieval framework for vector, BM25, hybrid, and rerank.
6. Add data-type registry.
7. Replace metadata raw content with typed raw content and collision-safe storage keys.
8. Add service-level batch ingest.
9. Make website adapter config-backed.
10. Clean up generation cache keys and prompt boundaries.

## Coding Rules

- Keep the core minimal.
- Prefer narrow protocols over concrete dependencies.
- Keep transport parsing separate from gateway validation.
- Keep adapter-specific fields inside adapters.
- Keep retriever-specific logic inside retrievers.
- Do not expose raw Qdrant filters to clients.
- Do not store user/provider API keys.
- Keep optional components explicitly optional.
