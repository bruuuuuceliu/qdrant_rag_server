# RAG Test Client Examples

These scripts mimic a client calling a running RAG deployment. They default to
the local ports used by `examples/local/run-all.sh`, and can also target a
remote server by setting environment variables or passing CLI flags.

## Defaults

- gRPC target: `127.0.0.1:50051`
- Retrieval HTTP base URL: `http://127.0.0.1:8081`
- project: `demo`
- user: `user_1`
- knowledge base: `demo`
- collection: `rag_demo_v1`

## Environment

```bash
export RAG_TEST_GRPC_TARGET=127.0.0.1:50051
export RAG_TEST_GRPC_SECURE=false
export RAG_TEST_HTTP_BASE_URL=http://127.0.0.1:8081
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

Run from the repository root after starting the local runtime:

```bash
python -m examples.test_client.test_1
python -m examples.test_client.test_2
python -m examples.test_client.test_3
python -m examples.test_client.test_4
python -m examples.test_client.test_5
```

The scripts cover:

- `test_1.py`: gRPC `HealthCheck`
- `test_2.py`: gRPC `Ingest`, then `GetIngestJobStatus`
- `test_3.py`: gRPC `Search`
- `test_4.py`: HTTP `POST /search` against the retrieval API
- `test_5.py`: HTTP `POST /documents/raw` against the retrieval API

Each script accepts common target overrides:

```bash
python -m examples.test_client.test_1 --grpc-target 127.0.0.1:50051
python -m examples.test_client.test_4 --http-base-url http://127.0.0.1:8081
python -m examples.test_client.test_3 --project-id demo --user-id user_1 --kb-id demo
```

`examples/local/run-all.sh` defaults to broker-first mode and exposes the
manager-compatible gRPC API on `50051`. Use `50052` only when you explicitly
start a separate project/RAG gRPC service, such as with `--external-project-service`.
