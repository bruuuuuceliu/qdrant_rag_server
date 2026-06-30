# RAG Test Client Examples

These scripts mimic a client calling a running RAG deployment. They default to
the local ports used by `examples/local/run-all.sh`, and can also target a
remote server by setting environment variables or passing CLI flags.

## Defaults

- gRPC target: `127.0.0.1:50051`
- project: `demo`
- user: `user_1`
- knowledge base: `demo`
- collection: `rag_demo_v1`

## Environment

```bash
export RAG_TEST_GRPC_TARGET=127.0.0.1:50051
export RAG_TEST_GRPC_SECURE=false
export RAG_TEST_PROJECT_ID=demo
export RAG_TEST_USER_ID=user_1
export RAG_TEST_KB_ID=demo
export RAG_TEST_DOC_ID=test_client_doc
export RAG_TEST_COLLECTION_NAME=rag_demo_v1
export RAG_TEST_TIMEOUT_SECONDS=30
```

For a remote TLS gRPC target:

```bash
export RAG_TEST_GRPC_TARGET=rag.example.com:443
export RAG_TEST_GRPC_SECURE=true
```

## Test Cases

Run the default broker-first gRPC flow from the repository root after starting
the local runtime:

```bash
python -m examples.test_client.test_1
python -m examples.test_client.test_2
python -m examples.test_client.test_3
```

The scripts cover:

- `test_1.py`: gRPC `HealthCheck`
- `test_2.py`: gRPC `Ingest`, then `GetIngestJobStatus`
- `test_3.py`: gRPC `Search`; empty result sets are valid by default, and
  `--require-chunks` enables a stricter smoke check.

Each script accepts common target overrides:

```bash
python -m examples.test_client.test_1 --grpc-target 127.0.0.1:50051
python -m examples.test_client.test_3 --project-id demo --user-id user_1 --kb-id demo
```

`examples/local/run-all.sh` exposes the manager-compatible gRPC API on `50051`.
Project planning and helper services communicate through Redpanda-compatible
topics behind that manager API.
