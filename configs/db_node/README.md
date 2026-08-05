# Database Node Config

This folder owns configuration for the database node (`db_node`).

The database node keeps the logical registry of the durable RAG stores in the
shared Postgres database. Its control-plane tables are:

- `db_node_databases`: logical database ownership, purpose, target schema, version, and state.
- `db_node_schema_versions`: service-reported schema version/checksum records.
- `db_node_allocations`: immutable allocation history for requested database names.
- `db_node_health_checks`: persisted readiness/health snapshots for allocated databases.

The node resolves its Postgres DSN from `DB_NODE_DB_URL`, falling back to
`RAG_POSTGRES_URL`. It must not import service internals or query service-owned
rows in normal runtime.
