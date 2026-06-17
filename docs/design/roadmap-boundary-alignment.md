# Roadmap Boundary Alignment

Section status: implementation accepted for the sixteenth development loop section.

## Requirement Document

The implementation roadmap still points directly from remote project/RAG
compatibility to a production broker adapter. Several service-boundary sections
have now been implemented: split manager clients, ingestion job acceptance,
ingestion preparation, retrieval index queueing, retrieval app contexts, local
manager adapters, and import guards. The roadmap should reflect this current
state so future loops follow the actual next boundary work.

Scope:

- Update `docs/implementation-roadmap.md` with the newly accepted boundary
  iterations.
- Keep the production broker adapter as pending future work.
- Preserve existing historical iteration notes.

Out of scope:

- Rewriting all architecture docs.
- Claiming physical service transport is complete.

## Acceptance Criteria

- Roadmap includes implemented sections for manager split clients, ingestion
  preparation/index publication, retrieval index worker/app, retrieval app
  context, local manager adapters, and boundary guards.
- Roadmap identifies independent retrieval/ingestion transport and project
  config/scope extraction as pending before production broker hardening.
- `progress.md` records the section result.

## Structure Design

Files changed in this section:

```text
docs/
  implementation-roadmap.md
  design/roadmap-boundary-alignment.md

progress.md
```

## Implementation Design

1. Update roadmap after Iteration 9 with the newly implemented boundary work.
2. Rename the old next iteration into a later pending milestone.
3. Keep wording conservative about compatibility behavior.
4. No code changes required.

## Review Checklist

- The roadmap distinguishes in-process contracts from physical service APIs.
- Pending work is not overstated as complete.
