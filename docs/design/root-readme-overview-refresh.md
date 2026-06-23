# Root README Overview Refresh

Status: accepted.

## Requirement

Refresh the root `README.md` so it is a useful first page for the project. It
must explain the current service-oriented retrieval platform, show the
architecture visually, show message flows visually, document local startup, and
avoid stale links or outdated monolithic RAG-server language.

The README should be clear about the current migration state: the local stack is
usable for development and smoke testing, while some physical service
boundaries still depend on compatibility composition.

## Acceptance Criteria

- The root README gives a concise project overview focused on retrieval-first
  behavior.
- Architecture visualization shows manager, project, ingestion, retrieval,
  workflow log, queues, Qdrant, cache, and storage.
- Message visualizations show ingest/index flow and search flow.
- Local runner documentation points to `examples/local/run-all.sh` and
  `examples/local/stop-all.sh`.
- Config documentation states that config code, env examples, and secrets live
  under `./configs`.
- Current limitations are called out explicitly.
- Documentation links in the root README resolve locally.

## Structure Design

```text
README.md
  project overview
  architecture Mermaid diagram
  service ownership table
  ingest/index Mermaid sequence
  search Mermaid sequence
  local split-service Mermaid diagram
  repository layout
  quick start
  configuration
  current status
  development and docs links

tests/test_docs_links.py
  include root README in local link validation
```

## Class Design

No runtime classes are required. This is a documentation-only section.

## Implementation Design

1. Replace stale root README content with the current service-oriented overview.
2. Add Mermaid diagrams for architecture and message sending flows.
3. Keep local startup and config paths aligned with the current runner and
   `configs` profile design.
4. Add the root README to documentation link validation.
5. Run focused docs tests and the full suite.

## Review Notes

- The README should not imply full production readiness.
- Diagrams should show current migration behavior without overloading the first
  page with every compatibility detail.
- The root README should link only to files that exist in this repository.
