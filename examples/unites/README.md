# Unite Showcases

These scripts are manual examples that exercise public service/node boundaries.
They are not replacement integration tests.

## Broker Round Trip

Requires live Redpanda and `aiokafka`:

```bash
python -m examples.unites.broker_roundtrip
```

The script bootstraps canonical broker topics with a unique topic prefix,
publishes one `MessageEnvelope`, and consumes it with a unique consumer group.
Configure Redpanda with `BROKER_BOOTSTRAP_SERVERS`; the default is
`127.0.0.1:9092`.

## SQLite Database CRUD

Runs with local files only:

```bash
python -m examples.unites.sqlite_database_crud
```

The SQLite node allocates the database and records schema/health metadata. The
example then performs create, read, update, and delete inside the allocated DB
as the owning service would. Configure the root with
`SQLITE_NODE_DATABASE_ROOT`; the default is `/tmp/qdrant_rag/sqlite`.

## Storage CRUD

Runs with local files only:

```bash
python -m examples.unites.storage_database_crud
```

The storage example uses `FilesystemStorageService` to put, get, delete, and
verify a missing read. Configure the root with `STORAGE_NODE_ROOT`; the default
is `/tmp/qdrant_rag/storage_node`.
