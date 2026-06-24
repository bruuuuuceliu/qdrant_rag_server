# Development Rules

This document defines how to develop and update this repository. It is about
engineering rules and working process, not feature behavior.

## Repository Rule

All servers stay in this one repository, but each independent server or node
must live in its own independent top-level folder. Do not split servers into
separate repositories unless that decision is made explicitly later.

Each server folder must be treated as its own workspace:

- Own source code.
- Own runtime entrypoint.
- Own dependency wiring.
- Own config loading boundary.
- Own tests.
- Own deployment/startup definition.

Services may share only stable external contracts and small generic utilities.
They must not share parent service classes, inherited server frameworks,
runtime composition code, repositories, handlers, or business logic.

## Folder Rules

- Put each independent server or node in a separate top-level folder.
- Put service-specific config under `configs/<service-or-node>/`.
- Put service-specific tests under `tests/<service-or-node>/`.
- Put cross-service integration tests under `tests/integration/`.
- Put durable design notes under `docs/design/` before or while changing code.
- Put implemented subsystem notes under `docs/implementations/` when behavior is
  complete enough to document.
- Keep shared code narrow: contracts, schemas, protocol clients, error codes,
  correlation IDs, and generic utilities only.

Do not place server-specific behavior in shared packages to avoid ownership
decisions. If code controls runtime behavior for one server, it belongs to that
server.

## Boundary Rules

- No service may import another service's internal modules.
- Services communicate through public APIs, broker topics, typed contracts,
  schemas, or config values.
- Runtime service-to-service communication must use the same production-style
  path in local and production.
- Local development means all real servers run on one machine. It does not mean
  embedded services, in-memory queues, file-based communication, or special
  local-only code paths.
- Unit tests may use fakes for isolated behavior. Runtime modes and integration
  tests must follow real service boundaries.

## Design Loop

Use this loop for any non-trivial architecture, service-boundary, config,
message, storage, or workflow change:

1. Read: inspect the current code, docs, tests, configs, and local runner paths
   before deciding the change shape.
2. Design: write or update the relevant design note with ownership, contracts,
   data flow, config impact, tests, and migration steps.
3. Review: compare the design against service boundaries, local-vs-production
   parity, config/test layout, and import rules.
4. Update design: fix contradictions before coding.
5. Implement: keep the code change scoped to the accepted design.
6. Document: update progress, architecture, contracts, or implementation docs
   when the actual behavior changes.

Do not use code as the first design document for boundary-changing work.

## Code Loop

Use this loop when implementing changes:

1. Code: make the smallest coherent change that moves the system toward the
   target boundary.
2. Test: run focused tests for the changed area first.
3. Review: inspect the diff for boundary violations, accidental coupling,
   config leakage, missing tests, and compatibility shims.
4. Debug: fix failing tests or design mismatches without widening the scope.
5. Review again: re-check imports, runtime paths, docs, and test coverage.
6. Broaden tests: run integration or larger suites when the change affects
   contracts, startup, config, or cross-service flow.

Do not stop after code compiles. A change is not done until its tests and docs
match the behavior.

## Documentation Rules

- Keep progress documents honest: separate implemented behavior, compatibility
  scaffolding, target design, and missing work.
- Update docs in the same change when code changes ownership, message flow,
  config, startup, or testing expectations.
- Prefer concrete implementation order over conceptual roadmaps.
- Keep diagrams professional and message-oriented when describing distributed
  flow.
- Do not hide open gaps. List missing work and how to improve it.
- Avoid documenting local shortcuts as target architecture.

## Progress Document Structure

`progress.md` must be the implementation control document for this repository.
It should show the real current state, the ordered development path, and the
architecture diagrams needed to keep work aligned.

Use this structure:

1. Overall Progress
   - A table with exactly these fields: `Area`, `Progress`, `Completed`, and
     `Missing`.
   - `Area` is a concrete subsystem or development concern.
   - `Progress` is an approximate percentage based on inspected code, tests,
     configs, docs, and runtime wiring.
   - `Completed` lists implemented behavior only.
   - `Missing` lists gaps that still block the ideal architecture.
2. Steps
   - A table with exactly these fields: `Step`, `Topic`, `Implementation`,
     `Acceptance Standard`, and `Status`.
   - Steps must be ordered by the required implementation sequence.
   - Development must follow these steps in order. Do not randomly pick later
     work unless the current step is complete or explicitly blocked.
   - `Implementation` must describe the real code/doc/test work to perform.
   - `Acceptance Standard` must be testable and tied to the target service
     topology.
   - `Status` must clearly say `Complete`, `Active`, `In progress`, `Pending`,
     or `Blocked`.
3. Graphs
   - Keep only diagrams that describe the target architecture, runtime shape,
     or task handling sequences.
   - Do not include graph duplicates of the progress tables, such as completion
     bar charts.
   - Do not include an extra message-communication graph when the same message
     shape is already covered by the target architecture and sequence graphs.

When updating `progress.md`, inspect the project before changing percentages or
statuses. The document must be generated from the gap between current code and
the ideal independent-server, broker-first structure.

## Config Rules

- Keep config separated by service or node.
- Local and production should differ only by addresses, credentials, ports,
  paths, and deployment values.
- Do not introduce local-only behavior through config.
- Keep secrets out of committed files.
- Add env examples when adding new required config values.
- Update config validation when new production-critical settings are added.

## Test Rules

- Service tests belong with the owning service's test folder.
- Integration tests must exercise public APIs, broker topics, or process
  boundaries, not cross-import internals.
- Add import-boundary tests when creating or changing service boundaries.
- Use fakes only for unit tests of isolated behavior.
- Use production-style communication paths for integration and local runtime
  tests.
- When changing contracts, test both valid and invalid messages.

### Minimal Test Set

Do not write tests just to increase test count. Every test must protect a stable
maintenance concern:

- A public contract, schema, message shape, or validation rule.
- A service boundary, import boundary, runtime entrypoint, or config ownership
  rule.
- Non-trivial business behavior, error handling, persistence, routing, or
  cross-service flow.
- A regression that has happened or is likely to happen again.

Do not add or keep tests that only prove implementation details:

- Phase, temporary, migration, or one-off smoke tests.
- Assertions that a variable was assigned, a file contains a string, or a helper
  factory passed through injected objects, unless that is the public contract.
- Duplicate coverage already proven by a smaller unit test or a higher-value
  integration test.
- Tests for trivial dataclass defaults, simple getters, or static documentation
  links unless those are production-critical contracts.

When adding a feature, prefer the smallest test set that would fail for a real
maintenance regression. Remove stale or duplicate tests in the same change when
the new coverage makes them redundant.

## Change Control Rules

- Keep changes scoped to the service or contract being changed.
- Do not refactor unrelated files while implementing a feature.
- Do not revert or overwrite unrelated existing changes.
- Remove compatibility shims only after the replacement path is implemented and
  tested.
- Mark compatibility paths clearly as temporary migration scaffolding.
- If a design decision changes, update the design docs before continuing code.

## Review Checklist

Before considering a change complete, verify:

- The owning server folder contains the behavior.
- No service imports another service's internals.
- Shared code contains only contracts or generic utilities.
- Config is under the correct config folder.
- Tests are under the correct test folder.
- Local runtime uses the same code path expected for production.
- Documentation reflects the actual current state and remaining gaps.
- Focused tests pass.
- Formatting and doc-link checks pass when docs changed.
