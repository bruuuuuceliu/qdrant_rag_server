# qdrant_retrieval_service Documentation

This project is a minimal, extensible information retrieval service. It can support RAG-style generation, but retrieval is the core product: ingest data, index it, search it, filter it, delete it, and report job status.

## Read First

- [Architecture](architecture.md): component boundaries and replaceable parts.
- [Service Boundaries](service-boundaries.md): manager/auth, domain services, helper nodes, task manager, and broker ownership.
- [Ideal System Boundary](boundary.md): target multi-service architecture, inputs, outputs, queues, and ownership stakes.
- [Contracts](contracts.md): manager routing and queue message contracts.
- [Development Rules](development.md): repository, design, code, test, review, and documentation workflow rules.
- [Implementation Roadmap](implementation-roadmap.md): iteration targets and migration guardrails.
- [Operations Runbook](operations.md): broker-first startup, readiness, and troubleshooting.
- [Implementation Documentation](implementations/README.md): implemented subsystem details and verification notes.
- [Section Design Index](design/section-design-index.md): accepted development loop sections and status docs.
- [Document handling module design](design/document-handling-module.md): proposed URL/file parsing and chunking architecture.
- [Agent Memory, Chat History, and User Profile Requirements](agent-memory-requirements.md): approved requirements for the RAG service as the chat platform's memory/knowledge layer — session recording, history compression, cross-source retrieval, and user profiles.
- [Examples](../examples/README.md): local startup and first ingest/search calls.
- [Configuration Profiles](../configs/README.md): local/production config modules, env files, and override order.

## Design Position

The project is being realigned to a strict independent-server design:

- Each server or worker lives in its own independent workspace.
- Runtime service work communicates through Redpanda topics; public APIs are
  limited to auth/status/health style boundaries.
- Services do not import another service's internals.
- Shared code contains contracts, schemas, protocol clients, and generic
  utilities only.
- Configs and tests are separated by service under `configs/` and `tests/`.
- Local and production use the same code paths; only addresses, credentials,
  ports, and paths differ.

The service surface should stay small:

- Core: ingest, retrieve, delete, status, cache invalidation, and optional raw backup.
- Optional: reranking, generation, object storage, version management.
- Current retrieval additions: Qdrant sparse BM25 and hybrid retrieval.
- Future: data-type registries, durable jobs, and typed raw content.

Components should be replaceable through narrow interfaces. The engine should orchestrate, not own every implementation detail.
