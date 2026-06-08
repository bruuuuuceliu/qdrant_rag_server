# qdrant_retrieval_service Documentation

This project is a minimal, extensible information retrieval service. It can support RAG-style generation, but retrieval is the core product: ingest data, index it, search it, filter it, delete it, and report job status.

## Read First

- [Overview](overview.md): purpose, current status, and core concepts.
- [Architecture](architecture.md): component boundaries and replaceable parts.
- [Data Model](data-model.md): project/user/KB/document/chunk structure and Qdrant payloads.
- [Workflows](workflows.md): ingest, search, delete, generation, health, and version flows.
- [API](api.md): current gRPC service shape.
- [Configuration](configuration.md): environment variables and runtime defaults.
- [Extension Guide](extension-guide.md): how to add adapters, data types, retrievers, storage, generation, and status backends.
- [Development](development.md): setup, tests, current limitations, and next implementation order.
- [LLM and embedding design](design/llm_embedding_design.md): provider boundaries for embeddings, generation, extraction, and reranking.
- [Examples](../examples/README.md): local startup and first ingest/search calls.

## Design Position

The service should stay small:

- Core: ingest, retrieve, delete, status, cache invalidation, and optional raw backup.
- Optional: reranking, generation, object storage, version management.
- Future: BM25, hybrid retrieval, data-type registries, durable jobs, and typed raw content.

Components should be replaceable through narrow interfaces. The engine should orchestrate, not own every implementation detail.
