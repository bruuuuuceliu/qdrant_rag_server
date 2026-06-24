# SQLite Node Config

This folder owns configuration for local SQLite database nodes.

SQLite may be used as a local durable database node for service-owned state such
as project config, ingestion jobs, workflow logs, or placement records. SQLite
must not be used as the runtime message broker substitute.

The SQLite node owns a metadata database named `_sqlite_node.db` under
`SQLITE_NODE_DATABASE_ROOT`. Its control-plane tables are:

- `db_node_databases`: logical database ownership, purpose, path, version, and state.
- `db_node_schema_versions`: service-reported schema version/checksum records.
- `db_node_allocations`: immutable allocation history for requested database paths.
- `db_node_health_checks`: persisted readiness/health snapshots for allocated databases.

Service-owned business tables remain inside their allocated database files.
The SQLite node must not import service internals or query service-private rows
in normal runtime.
