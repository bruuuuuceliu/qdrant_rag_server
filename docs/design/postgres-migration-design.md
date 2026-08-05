# Postgres access layer design

> **Status: CUTOVER COMPLETE.** Postgres is now the always-on backend for every
> RAG durable store; SQLite repositories and tests have been removed. This
> document is retained as the historical access-layer design reference.

Design for the Postgres implementations of the seven RAG durable stores.
Companion to `docs/design/postgres-migration-plan.md` (store map, semantics to
preserve, sequencing). This document fixes the access-layer decisions: driver,
pooling, migration strategy, per-store schema mapping, and backend selection.

Each store keeps its repository protocol and its Postgres implementation, with
the durable-store DSN resolved from `RAG_POSTGRES_URL` (or a per-store
`*_DB_URL` override) at the wiring composition root.

## 1. Driver: psycopg 3 (`psycopg[binary]` + `psycopg-pool`)

`psycopg[binary]>=3.1` and `psycopg-pool>=3.2` are added to the base
dependencies in `pyproject.toml`.

| Criterion | psycopg 3 | asyncpg |
|---|---|---|
| Async support | `AsyncConnection` / `AsyncCursor` | native `asyncpg.connect` |
| Sync support | sync `Connection` | none |
| Pool | `psycopg_pool.AsyncConnectionPool` + `ConnectionPool` | built-in pool |
| Python 3.12 asyncio | supported | supported |
| Install | binary wheel, no toolchain | C extension build |
| JSON adaptation | native `Json` / `Jsonb` wrappers | `jsonb` codec |

asyncpg only covers the async stores; the placement registry is a synchronous
store (its resolver and all registry methods are sync today), so asyncpg would
force a second driver just for that seam. One psycopg 3 dependency covers both
halves: `AsyncConnection` for the six async stores and sync `Connection` for
placement. psycopg 3 also removes the `shared/executor.AsyncExecutor`
thread-pool hop that project config and ingest jobs use to route their blocking
SQLite calls.

## 2. Connection pooling

One `AsyncConnectionPool` per store, built in the wiring composition root from
the store's `*_DB_URL` DSN, and closed on service shutdown:

- DSN: `postgresql://<user>:<pass>@<host>:5432/<db>`, from `*_DB_URL`.
- Pool: `psycopg_pool.AsyncConnectionPool(dsn, min_size=1, max_size=5, open=False)`,
  opened explicitly (`await pool.open()` + `await pool.wait()` so first queries
  do not pay the connection cost), closed in the service shutdown path
  (`await pool.close()`).
- Repos acquire a connection per call via `async with pool.connection() as conn`,
  mirroring the current per-call `sqlite3.connect`.
- Placement stays synchronous: a short-lived psycopg sync `Connection` per call,
  mirroring its current per-call `sqlite3.connect`. No pool.

Each store is a separate service process on its own connection, so one pool per
store is also one pool per process — no cross-process sharing, matching the
single-writer SQLite ownership model today.

## 3. Migration strategy: inline idempotent DDL, no Alembic

No Alembic. The repos already self-initialize at startup with `CREATE TABLE IF
NOT EXISTS` plus idempotent in-place migrations; the Postgres repos mirror that
pattern exactly:

- `CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`.
- Postgres partial unique indexes map one-to-one onto the SQLite partial index:
  `CREATE UNIQUE INDEX IF NOT EXISTS uq_user_facts_one_active
   ON user_facts (user_id, fact_type, subject) WHERE status = 'active'`.
- In-place column additions use `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` (or
  `information_schema` checks) where a SQLite migration today rebuilds/ALTERs a
  table; the three `memory_records` migrations (document kind, `collection_name`/
  `metadata_json`, `indexed`) fold into the base `CREATE TABLE` for a fresh
  Postgres schema and keep their idempotent guards for pre-existing ones.
- `AUTOINCREMENT` maps to `BIGINT GENERATED ALWAYS AS IDENTITY`; `INSERT OR
  IGNORE`/`INSERT OR REPLACE` map to `ON CONFLICT ... DO NOTHING`/`DO UPDATE`;
  `ON CONFLICT(project_id) DO UPDATE` already exists in SQL.
- `CREATE TABLE` and `CREATE UNIQUE INDEX` are idempotent by construction, so
  the initialize() call stays a startup no-op on a warm database, exactly like
  SQLite.

Alembic would add a migration tool, a version table, and a second schema source
of truth for stores that today create their own schema at startup. At this
scale (seven stores, single-writer, startup idempotent DDL) it is more machinery
than value.

## 4. Per-store schema mapping

Column types stay byte-identical to SQLite: ISO strings stay `TEXT`, epoch-float
timestamps stay `DOUBLE PRECISION` (SQLite `REAL` is an 8-byte float), and JSON
columns stay `TEXT`. No `TIMESTAMPTZ`, no `JSONB`.

**JSON as `TEXT`, not `JSONB`.** Every repo already serializes its JSON fields
with `json.dumps(..., sort_keys=True)` and reads them with `json.loads`; the
Postgres repos reuse those exact round-trips. `TEXT` preserves the stored bytes
identical to SQLite and keeps the repo read/write paths unchanged. `JSONB`
canonicalizes key order, whitespace, and numeric types, which would change the
stored bytes versus SQLite and buys nothing — no query filters inside a JSON
column today. psycopg's `Jsonb` adapter remains available if a store later
needs in-JSON predicates.

`sqlite3.Row` column access (`row["col"]`) maps to psycopg's `dict_row` row
factory, so the existing `_x_from_row` helpers port directly.

| # | Store | Postgres tables (key columns) | Notes |
|---|-------|-------------------------------|-------|
| 1 | agent memory | `sessions` (session_id PK), `messages` (message_id PK, UNIQUE(session_id, sequence_number)), `memory_records` (memory_id PK, kind CHECK incl. `document`, `indexed`), `user_profiles` (user_id PK), `user_facts` (fact_id PK, partial unique `uq_user_facts_one_active` on (user_id, fact_type, subject) WHERE status='active'), `idempotency_records` (PK (owner_user_id, idempotency_key)) | `supersede_fact` locks the active rows with `SELECT ... FOR UPDATE` inside the transaction instead of the SQLite write lock, then inserts; a `UniqueViolation` on the partial index raises `FactSupersessionConflict`. |
| 2 | task execution | `task_executions` (task_id PK), `task_steps`, `task_step_attempts` (id BIGINT IDENTITY), `task_results` (task_id PK) | Lease claim: `SELECT ... FOR UPDATE SKIP LOCKED` on the candidate `task_steps`, then the existing conditional `UPDATE ... WHERE ...` with a rowcount check (or `RETURNING`). Ordering on `task_step_attempts.id` preserves the AUTOINCREMENT order. Legacy `task_states` import stays. |
| 3 | project config | `projects` (project_id PK, chunker/retrieval/cache `_config_json` TEXT) | `ON CONFLICT(project_id) DO UPDATE` unchanged. Async driver removes the `AsyncExecutor` hop. |
| 4 | workflow log | `workflow_log_entries` (id BIGINT IDENTITY, headers_json TEXT, payload_json TEXT) | Append/list `ORDER BY id ASC`. |
| 5 | ingest jobs | `ingestion_jobs` (job_id PK, metadata_json TEXT, created_at/updated_at DOUBLE PRECISION) | `INSERT OR REPLACE` → `ON CONFLICT(job_id) DO UPDATE`. Async driver removes the `AsyncExecutor` hop. |
| 6 | placement | `retrieval_shards` (shard_id PK), `retrieval_placements` (placement_id PK, replica_shard_ids_json TEXT), `retrieval_routing_policies` (project_id PK) | Synchronous psycopg `Connection` per call. `next_version()` = `COALESCE(MAX(placement_version), 0) + 1`. |
| 7 | response cache | `responses` (PK (project_id, user_id, cache_key), expires_at DOUBLE PRECISION) | `INSERT OR REPLACE` → `ON CONFLICT(project_id, user_id, cache_key) DO UPDATE`. |

## 5. Backend selection: `*_DB_URL` present -> Postgres, else SQLite

Each settings dataclass gains a `db_url: str | None = None` field next to its
`db_path` field, read from the mirroring env var:

`MEMORY_DB_URL`, `TASK_SERVICE_STATE_DB_URL`, `PROJECT_CONFIG_DB_URL`,
`WORKFLOW_LOG_DB_URL`, `INGESTION_JOB_DB_URL`, `RETRIEVAL_PLACEMENT_DB_URL`,
`RAG_RESPONSE_CACHE_DB_URL`.

An unset or blank `*_DB_URL` resolves to `None` (read through the existing
`configs.base.get_optional_value` / `values.get` pattern), so a store stays on
SQLite unless a URL is explicitly populated.

Selection happens only in the wiring composition root, as a one-line branch:

```python
repository = (
    PostgresMemoryRepository(settings.db_url)
    if settings.db_url
    else SQLiteMemoryRepository(settings.db_path)
)
```

Both implementations satisfy the same repository protocol and expose the same
`initialize()`. Domain handlers never see the backend. The empty default keeps
SQLite the behavior when no `*_DB_URL` is set, so existing deployment and test
environments are unchanged.

## 6. Compose postgres service

Add a `postgres` service to `deployment/docker-compose.prod.yml`, on
`rag-internal` (the worker-ops network) with the existing infra genre —
postgres is a RAG-internal store, never on the SA-shared `rag-memory-test`:

```yaml
postgres:
  image: postgres:16-alpine
  environment:
    POSTGRES_USER: ${POSTGRES_USER:-rag}
    POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}
    POSTGRES_DB: ${POSTGRES_DB:-rag}
  networks: [rag-internal]
  volumes:
    - postgres-data:/var/lib/postgresql/data
  healthcheck:
    test: ["CMD-SHELL", "pg_isready -U \"$$POSTGRES_USER\" -d \"$$POSTGRES_DB\""]
    interval: 5s
    timeout: 3s
    retries: 10
```

- `postgres-data:` joins the existing volume block (rag-data, redpanda-data,
  redis-data, qdrant-data, ...).
- `x-rag-env` gains the seven `*_DB_URL` vars, empty by default (e.g.
  `MEMORY_DB_URL: "${MEMORY_DB_URL:-}"`), so the compose stack keeps running on
  SQLite unless a store is opted in. A populated URL points at
  `postgresql://rag:${POSTGRES_PASSWORD}@postgres:5432/rag`.
- `x-rag-service` depends_on `postgres: {condition: service_healthy}` so workers
  wait for the DB when a URL is set; the dependency is inert while the vars are
  empty.
- `POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB` and the seven `*_DB_URL`
  vars (empty by default) are added to `deployment/compose.prod.env.example`
  and each `configs/*/local.env.example`.

## 7. Rationale

- **Minimal.** One driver, no Alembic, no new module tree: each Postgres repo is
  a sibling class in its store's existing repository module, and selection is a
  one-line branch in the existing composition roots. Column types and JSON
  storage are chosen for byte parity with SQLite so repo read/write paths port
  without rewriting.
- **Genre-consistent.** Startup idempotent `CREATE TABLE IF NOT EXISTS`
  initialization, per-store settings dataclasses driven by `configs` env files,
  and a postgres compose service that mirrors redis/qdrant (alpine image, named
  volume, pg_isready healthcheck, rag-internal) all follow the existing patterns.
- **Additive.** Protocols, SQLite implementations, broker contracts, domain
  handlers, and existing tests are untouched. SQLite is the default and the
  fallback; Postgres is opt-in per store via env. The six async stores gain a
  real async driver (removing the `AsyncExecutor` thread-pool hop in project
  config and ingest jobs), and the concurrency-sensitive stores (memory fact
  supersession, task lease claims) get row-lock / `SKIP LOCKED` equivalents
  with identical semantics.
