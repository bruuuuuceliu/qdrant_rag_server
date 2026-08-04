# Postgres migration sprint plan

Sprint goal: add a Postgres backend alongside the seven RAG SQLite stores, selected
per store via env at the wiring composition root, with SQLite remaining the default
and the fallback. Ship Postgres implementations of all seven stores (agent memory
first as the SA-integration reference), a postgres compose service, and per-store
`*_DB_URL` settings — all verified by running tests against both backends, with
existing SQLite behavior and tests untouched.

Companion to `docs/design/postgres-migration-design.md`, which fixes the access-layer
decisions (driver, pooling, migration strategy, schema mapping, backend selection).
This document is the store map, semantics to preserve, sequencing, and acceptance
criteria.

## Store map

All seven RAG SQLite stores with protocol (port), SQLite implementation, wiring
point, and path setting. Line numbers are the current truth on `connection`.

| # | Store | Protocol (port) | SQLite impl | Wiring point | Path env (setting) | Default | Compose ref |
|---|-------|-----------------|-------------|--------------|--------------------|---------|-------------|
| 1 | Agent memory | `MemoryTransaction` + `MemoryRepository` (`memory_service/repository.py:41,87`) | `SQLiteMemoryTransaction` (`memory_service/repository.py:485`), `SQLiteMemoryRepository` (`memory_service/repository.py:716`) | `memory_service/domain_app.py:209` (`create_default_domain_app`) | `MEMORY_DB_PATH` (`memory_service/config.py:126`) | `/var/lib/rag/agent_memory.db` (`memory_service/config.py:29`) | `:335` |
| 2 | Task execution | `TaskStateRepository` (`task_service/repository.py:55`) | `SQLiteTaskStateRepository` (`task_service/repository.py:317`) | `task_service/app.py:61` | `TASK_SERVICE_STATE_DB_PATH` (`task_service/config.py:45`) | `examples/local/.data/task_service_state.db` (`task_service/config.py:20`) | `:260` |
| 3 | Project config | none (concrete class; re-exported via `project_service/config/__init__.py` and `configs/project/repository.py`) | `SQLiteProjectConfigRepository` (`project_service/config/repository.py:65`) | `project_service/domain_app.py:134` | `PROJECT_CONFIG_DB_PATH` (`project_service/domain_app.py:122`) | `/var/lib/rag/config.db` (`project_service/config/repository.py:19`) | `:273` |
| 4 | Workflow log | `WorkflowLogRepository` (`workflow_log_service/repository.py:13`) | `SQLiteWorkflowLogRepository` (`workflow_log_service/repository.py:40`) | `workflow_log_service/domain_app.py:159` | `WORKFLOW_LOG_DB_PATH` (`workflow_log_service/domain_app.py:148`) | `/var/lib/rag/workflow_log.db` (`workflow_log_service/domain_app.py:131`) | `:285` |
| 5 | Ingest jobs | `IngestionJobRepository` (`ingestion_service/jobs/repository.py:12`) | `SQLiteIngestionJobRepository` (`ingestion_service/jobs/sqlite.py:21`) | `ingestion_service/server/worker.py:48` | `INGESTION_JOB_DB_PATH` (`configs/ingestion/config.py:34`) | `/var/lib/rag/ingestion_jobs.db` (`configs/ingestion/config.py:19`) | `:297` |
| 6 | Placement | `RetrievalShardRepository` / `PlacementRepository` / `RoutingPolicyRepository` (`retrieval_service/placement/repository.py:17,27,37`) | `SQLitePlacementRegistry` (`retrieval_service/placement/repository.py:144`) | `retrieval_service/indexing/worker.py:183` and `retrieval_service/server/worker.py:254` (both only when `RETRIEVAL_PLACEMENT_ENABLED`) | `RETRIEVAL_PLACEMENT_DB_PATH` (`configs/base.py:165`) | `/tmp/qdrant_rag/placement.db` (`configs/base.py:55`) | `:94` (`x-rag-env`) |
| 7 | Response cache (Tier 2) | none | `Tier2ResponseCache` (`retrieval_service/services/cache.py:112`) | `retrieval_service/server/worker.py:208` | `RAG_RESPONSE_CACHE_DB_PATH` (`configs/base.py:122`) | `/var/lib/rag/response_cache.db` (`retrieval_service/services/cache.py:30`, `configs/base.py:122`) | `:92` (`x-rag-env`) |

Compose refs are the `*_DB_PATH` env line in `deployment/docker-compose.prod.yml`:
stores 6 and 7 live in the shared `x-rag-env` block (lines 92/94); stores 1-5 in their
service blocks.

### Semantics each Postgres store must preserve

- **Memory (1):** write ops run inside one `BEGIN IMMEDIATE` transaction
  (`transaction()` context manager, `isolation_level=None` + manual
  commit/rollback). `supersede_fact` (repository.py:661) relies on the SQLite write
  lock to serialize concurrent supersessions and on the partial unique index
  `uq_user_facts_one_active` to enforce one active fact per `(user_id, fact_type,
  subject)`. Inserts use `INSERT OR IGNORE` / integrity-error-as-False. `memory_records`
  carries three idempotent migrations (document kind, `collection_name`/`metadata_json`,
  `indexed`).
- **Task (2):** `claim_due_helper_dispatches` (repository.py:638) is a SELECT-then-
  conditional-UPDATE lease claim; ordering is `task_step_attempts.id` (AUTOINCREMENT).
  Has a legacy `task_states` import migration (`_migrate_legacy_task_states`).
- **Project (3):** single `projects` table; `ON CONFLICT(project_id) DO UPDATE`.
  Blocking calls route through `shared/executor.AsyncExecutor` (injected executor);
  an async Postgres driver removes the thread-pool hop.
- **Workflow log (4):** append/list ordered by `id ASC` (AUTOINCREMENT).
- **Ingest jobs (5):** `INSERT OR REPLACE`; `REAL` timestamps; `metadata_json` blob;
  optional `AsyncExecutor` hop.
- **Placement (6):** the only synchronous store — all registry methods are sync and
  the resolver (`retrieval_service/placement/resolver.py`) is sync, so its Postgres
  backend stays synchronous. `next_version()` is `MAX()+1`.
- **Cache (7):** `INSERT OR REPLACE` on composite PK `(project_id, user_id, cache_key)`;
  `REAL` `expires_at`.

## Postgres contract

- **Driver:** `psycopg[binary]>=3.1` + `psycopg-pool>=3.2` added to the base
  dependencies in `pyproject.toml` (no postgres driver present today — verified).
  One driver covers both halves: `AsyncConnection` / `AsyncConnectionPool` for the
  six async stores and sync `Connection` for placement, so no second driver is
  needed at the sync seam.
- **Pool:** one `AsyncConnectionPool` per store, built in the wiring composition root
  from the store's `*_DB_URL` DSN (`postgresql://<user>:<pass>@<host>:5432/<db>`),
  `min_size=1, max_size=5, open=False`, opened explicitly (`await pool.open()` +
  `await pool.wait()`), closed on service shutdown. Repos acquire per call via
  `async with pool.connection()`. Placement uses a short-lived sync `Connection` per
  call, mirroring its per-call `sqlite3.connect`. One pool per store = one pool per
  process, matching the single-writer SQLite ownership model.
- **Migration strategy:** mirror the existing inline idempotent `initialize()`
  pattern — `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` plus
  idempotent column/constraint checks at startup. No Alembic. Postgres partial unique
  indexes (`WHERE status = 'active'`) map onto the SQLite partial index; `AUTOINCREMENT`
  → `BIGINT GENERATED ALWAYS AS IDENTITY`; `INSERT OR IGNORE`/`INSERT OR REPLACE` →
  `ON CONFLICT ... DO NOTHING`/`DO UPDATE`; the three `memory_records` migrations fold
  into the base `CREATE TABLE` for a fresh schema and keep their idempotent guards
  for pre-existing ones.
- **Backend selection:** per-store `*_DB_URL` env var. When set, the wiring
  composition root builds the Postgres repo; otherwise the existing SQLite repo with
  `*_DB_PATH`. Selection lives only in the composition root (config + wiring), never
  in domain handlers or repository protocols. Empty default keeps SQLite as the
  behavior in every existing deployment and test environment.
- **Concurrency parity:** memory `supersede_fact` uses `SELECT ... FOR UPDATE` on the
  active rows inside the transaction instead of the SQLite write lock; task lease
  claims use `SELECT ... FOR UPDATE SKIP LOCKED` / atomic `UPDATE ... WHERE ...
  RETURNING`.
- **Row access parity:** `sqlite3.Row` column access (`row["col"]`) maps to psycopg's
  `dict_row` row factory, so the `_x_from_row` helpers port directly. JSON columns
  stay `TEXT` (byte-identical to SQLite, no `JSONB` canonicalization); epoch-float
  timestamps stay `DOUBLE PRECISION`.

### New env vars (mirror each `*_DB_PATH`)

`MEMORY_DB_URL`, `TASK_SERVICE_STATE_DB_URL`, `PROJECT_CONFIG_DB_URL`,
`WORKFLOW_LOG_DB_URL`, `INGESTION_JOB_DB_URL`, `RETRIEVAL_PLACEMENT_DB_URL`,
`RAG_RESPONSE_CACHE_DB_URL`. Each settings dataclass gains a `db_url: str | None =
None` field next to its `db_path` field.

### Compose

Add a `postgres` service to `deployment/docker-compose.prod.yml` —
`postgres:16-alpine`, `POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB` env, a
`postgres-data:` named volume joining the existing volume block, a `pg_isready`
healthcheck, on `rag-internal` (postgres is a RAG-internal store, never on the
SA-shared `rag-memory-test`). Add the seven `*_DB_URL` vars (empty by default) to
`x-rag-env` and to `deployment/compose.prod.env.example` plus each
`configs/*/local.env.example`; `x-rag-service` gains `depends_on: postgres:
{condition: service_healthy}` (inert while the URLs are empty).

## Sequencing

Memory first — it is the SA-integration-critical store and the reference the other
stores follow.

0. **Foundation.** Add `psycopg[binary]`/`psycopg-pool` to `pyproject.toml`; add the
   `postgres` compose service + volume + healthcheck + the seven `*_DB_URL` settings
   fields and env examples. Verify `docker compose config` and `pg_isready` on the
   new service.
1. **Agent memory (reference).** `PostgresMemoryRepository` + `PostgresMemoryTransaction`
   implementing the existing protocols, incl. `FOR UPDATE` fact supersession, partial
   unique index, and the three `memory_records` migrations; wiring factory in
   `memory_service/domain_app.py` selecting on `MEMORY_DB_URL`; Postgres repo test
   module.
2. **Task execution.** `PostgresTaskStateRepository` incl. `SKIP LOCKED` lease claim
   and legacy-state import; wiring in `task_service/app.py`.
3. **Project config.** `PostgresProjectConfigRepository`; wiring in
   `project_service/domain_app.py`.
4. **Workflow log.** `PostgresWorkflowLogRepository`; wiring in
   `workflow_log_service/domain_app.py`.
5. **Ingest jobs.** `PostgresIngestionJobRepository`; wiring in
   `ingestion_service/server/worker.py`.
6. **Retrieval stores.** `PostgresTier2ResponseCache` and `PostgresPlacementRegistry`
   (sync); wiring in `retrieval_service/server/worker.py` and
   `retrieval_service/indexing/worker.py`.
7. **Regression.** Full suite + ruff + dual-backend parity smoke.

## Acceptance criteria

Verifiable and concrete:

- Full `pytest -q` passes with no changes to existing tests (SQLite behavior
  preserved).
- `docker compose -f deployment/docker-compose.prod.yml config -q` valid; the
  `postgres` service reports healthy (`pg_isready`).
- New per-store Postgres repo tests pass against the compose `postgres` service,
  covering CRUD plus the store-specific semantics: memory idempotency-reuse conflict,
  single-active-fact supersession under concurrency, pending-index re-drive list +
  mark, task lease claim, placement version bump.
- Backend selection proven: the same store runs against SQLite with only `*_DB_PATH`
  set and against Postgres with only `*_DB_URL` set, with no code change beyond env —
  same tests, both backends.
- `ruff check` clean on touched files; `coverage fail_under=50` still met.
- Scope guard: `git diff --stat` touches only the data-access layer
  (`memory_service/repository.py`, `task_service/repository.py`,
  `project_service/config/repository.py`, `workflow_log_service/repository.py`,
  `ingestion_service/jobs/sqlite.py`, `retrieval_service/placement/repository.py`,
  `retrieval_service/services/cache.py`), config (`configs/*`,
  `memory_service/config.py`, `task_service/config.py`), wiring
  (`*_service/domain_app.py`, `*_service/app.py`, `*_service/server/worker.py`,
  `*_service/indexing/worker.py`), `pyproject.toml`, and
  `deployment/docker-compose.prod.yml` + env examples. No `broker_service`,
  `shared/contracts`, `*_domain_handler.py`, Qdrant/vector-store code, `storage_node`,
  `sqlite_node`, `redis_status_node`, `manager_service`, or SA files.

## Scope guard

Feature-adding, not rebuild: Postgres implementations are added alongside the SQLite
repositories; SQLite behavior, protocols, broker contracts, domain handlers, and
tests keep passing unchanged. The migration touches only the data-access layer,
config, wiring, and the compose `postgres` service. No `git commit`/`push`/`branch`;
changes stay uncommitted on `connection`.
