# qdrant_retrieval_service Documentation

This project is a minimal, extensible information retrieval service. It can support RAG-style generation, but retrieval is the core product: ingest data, index it, search it, filter it, delete it, and report job status.

## Read First

- [Architecture](architecture.md): component boundaries and replaceable parts.
- [Service Boundaries](service-boundaries.md): manager, project, ingestion, retrieval, and future service ownership.
- [Ideal System Boundary](boundary.md): target multi-service architecture, inputs, outputs, queues, and ownership stakes.
- [Contracts](contracts.md): manager routing and queue message contracts.
- [Implementation Roadmap](implementation-roadmap.md): iteration targets and migration guardrails.
- [Implementation Documentation](implementations/README.md): implemented subsystem details and verification notes.
- [Section Design Index](design/section-design-index.md): accepted development loop sections and status docs.
- [Document handling module design](design/document-handling-module.md): proposed URL/file parsing and chunking architecture.
- [Examples](../examples/README.md): local startup and first ingest/search calls.

## Design Position

The service should stay small:

- Core: ingest, retrieve, delete, status, cache invalidation, and optional raw backup.
- Optional: reranking, generation, object storage, version management.
- Current retrieval additions: Qdrant sparse BM25 and hybrid retrieval.
- Future: data-type registries, durable jobs, and typed raw content.

Components should be replaceable through narrow interfaces. The engine should orchestrate, not own every implementation detail.
