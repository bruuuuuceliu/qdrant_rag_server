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

## Database Node CRUD

Requires a reachable Postgres:

```bash
python -m examples.unites.db_node_database_crud
```

The database node registers the logical database and records schema/health
metadata in the shared Postgres database. The example then performs create,
read, update, and delete in the RAG Postgres database as the owning service
would. Configure the DSN with `RAG_POSTGRES_URL` (default
`postgresql://rag:rag@localhost:5432/rag`).

## Storage CRUD

Runs with local files only:

```bash
python -m examples.unites.storage_database_crud
```

The storage example uses `FilesystemStorageService` to put, get, delete, and
verify a missing read. Configure the root with `STORAGE_NODE_ROOT`; the default
is `/tmp/qdrant_rag/storage_node`.

## Client-To-Server Showcases

The `examples/test_client/` folder contains runnable scripts that mimic a client
calling a running local or remote RAG deployment:

```bash
python -m examples.test_client.test_1  # gRPC health
python -m examples.test_client.test_2  # gRPC ingest + status
python -m examples.test_client.test_3  # gRPC search
```

By default they target `examples/local/run-all.sh` ports. Override with
`RAG_TEST_GRPC_TARGET` or matching CLI flags.
