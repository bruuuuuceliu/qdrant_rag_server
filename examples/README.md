# Examples: Getting Started

This guide shows the shortest path to start the local RAG platform and try the
manager-compatible gRPC ingest/search flow.

## Architecture

```text
client
  -> manager_service gRPC API
  -> Redpanda task intake
  -> task_manager_service
  -> task_service
  -> project_service planning
  -> helper services for ingestion, storage, retrieval, and indexing
  -> Redis task status
```

The manager accepts public requests and publishes task intake messages. Project
planning and helper execution happen behind Redpanda-compatible topics. The
manager reads task status from Redis for status checks.

## Local Start

From the repository root:

```bash
examples/local/run-all.sh --reset --init
```

This starts local Redpanda, Redis, Qdrant when needed, task services, domain
services, helper workers, and the manager gRPC API on `127.0.0.1:50051`.

Stop local services with:

```bash
examples/local/stop-all.sh --clean
```

Useful variants:

```bash
examples/local/run-all.sh --init --no-server
examples/local/run-all.sh --infra-only
examples/local/run-all.sh --reset --init --no-qdrant
examples/local/run-all.sh --init --embedding-provider openrouter --embedding-model your-embedding-model --embedding-dimension 1536
```

For remote/OpenRouter-compatible embeddings, provide an embedding API key:

```bash
export RAG_EMBEDDING_API_KEY=sk-or-your-key
examples/local/run-all.sh --init --embedding-provider openrouter --embedding-model your-embedding-model --embedding-dimension 1536
```

## Test Client

After the local stack is running:

```bash
python -m examples.test_client.test_1
python -m examples.test_client.test_2
python -m examples.test_client.test_3
```

The scripts cover health, ingest/status, and search through the manager gRPC
API. The ingest status helper accepts in-flight broker statuses such as
`accepted`, `queued`, `running`, and `dispatched`, then waits for `completed` or
`failed` when the script needs a terminal result.

## Direct gRPC Shape

The compatibility gRPC protobuf package currently remains under
`shared.transport.grpc.generated`. Clients still call the manager gRPC
server on port `50051`.

```python
import asyncio
import grpc

from shared.transport.grpc.generated import (
    retrieval_service_pb2,
    retrieval_service_pb2_grpc,
)


async def main():
    async with grpc.aio.insecure_channel("localhost:50051") as channel:
        client = retrieval_service_pb2_grpc.RagServiceStub(channel)
        response = await client.Ingest(
            retrieval_service_pb2.IngestRequest(
                project_id="demo",
                user_id="user_1",
                kb_id="demo",
                doc_id="hello_doc",
                source_uri="memory://hello_doc",
                content_type="text/plain",
                metadata={"raw_text": "Hello world."},
            )
        )
        print(response)


asyncio.run(main())
```

## Unit Showcases

Standalone examples that do not require the full local stack:

```bash
python -m examples.unites.ingestion
python -m examples.unites.llm_generation
```

## Troubleshooting

Install runtime dependencies:

```bash
python -m pip install -e ".[dev]"
```

Check Qdrant:

```bash
curl http://localhost:6333/collections
```

If search returns no chunks, confirm the ingest task reached `completed`, the
project config was seeded with `--init`, and the search uses the same
`project_id`, `user_id`, and `kb_id` as the ingest request.
