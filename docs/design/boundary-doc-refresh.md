# Boundary Documentation Refresh

Section status: implementation accepted for the fifteenth development loop section.

## Requirement Document

The code now has manager split-client composition, ingestion-owned job
acceptance and preparation metadata, retrieval index queue commands/consumers,
retrieval app contexts, and boundary guard tests. The roadmap and architecture
docs still describe some of this work as future or only compatibility-based.

This section refreshes boundary documentation so it matches the accepted
implementation sections.

Scope:

- Update `docs/implementation-roadmap.md` with the newly accepted iterations.
- Update `docs/architecture.md` communication text for `retrieval.index`.
- Update `docs/service-boundaries.md` for ingestion/retrieval current behavior.

Out of scope:

- Rewriting `docs/boundary.md`.
- Adding new implementation behavior.

## Acceptance Criteria

- Roadmap records manager split clients and retrieval index queue worker as
  implemented.
- Architecture docs list `retrieval.index.requests` as current local queue work.
- Service-boundary docs mention ingestion publishing prepared chunks when
  configured and retrieval owning the index consumer/app context.
- `progress.md` records the section result.

## Structure Design

Files changed in this section:

```text
docs/
  architecture.md
  implementation-roadmap.md
  service-boundaries.md
  design/boundary-doc-refresh.md

progress.md
```

## Implementation Design

1. Add roadmap iterations for manager split clients and retrieval index queue.
2. Refresh architecture communication bullets.
3. Refresh service-boundary current behavior sections.
4. Run a quick documentation grep for stale `future retrieval.index` phrasing.

## Review Checklist

- Docs distinguish local implemented behavior from physical independent
  production services.
- No production-ready claims are added.
- Compatibility limitations remain explicit.
