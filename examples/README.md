# Examples: Getting Started

This guide shows the shortest practical path to start the local retrieval service and try ingest/search.

The project is still a prototype. The app path needs real dependencies such as Qdrant, gRPC, and sentence-transformers installed in the active environment.

## One-Line Local Start

From the repository root:

```bash
examples/local/start.sh --init
```

This command:

- activates the `evo` conda environment when available
- sets local `/tmp/qdrant_rag` database paths
- checks whether Qdrant is reachable
- initializes a demo project config when `--init` is provided
- starts `python -m rag_server.app`

Useful variants:

```bash
examples/local/start.sh --init --project-id demo
examples/local/start.sh --init --no-server
examples/local/start.sh --init --grpc-port 50052
examples/local/start.sh --init --embedding-provider openrouter --embedding-model your-embedding-model --embedding-dimension 1536
examples/local/start.sh --init --generation
```

For remote/OpenRouter-compatible embeddings, provide an embedding API key:

```bash
export RAG_EMBEDDING_API_KEY=sk-or-your-key
examples/local/start.sh --init --embedding-provider openrouter --embedding-model your-embedding-model --embedding-dimension 1536
```

Remote embeddings avoid local sentence-transformer calculation. The embedding model dimension must match `--embedding-dimension`, because Qdrant collections are created with that vector size.

## 1. Activate Environment

Use the project environment:

```bash
source /home/bruce/miniconda3/etc/profile.d/conda.sh
conda activate evo
```

Install the project:

```bash
python -m pip install -e ".[dev]"
```

## 2. Start Qdrant

If Docker is available:

```bash
docker run --rm -p 6333:6333 -p 6334:6334 qdrant/qdrant
```

The default server config expects Qdrant at:

```text
localhost:6333
```

## 3. Create Local Runtime Directories

The default `.env.example` uses `/var/lib/rag`, which may require elevated permissions. For local development, use `/tmp` paths:

```bash
export RAG_CONFIG_DB_PATH=/tmp/qdrant_rag/config.db
export RAG_RESPONSE_CACHE_DB_PATH=/tmp/qdrant_rag/response_cache.db
export RAG_GRPC_PORT=50051
export RAG_QDRANT_HOST=localhost
export RAG_QDRANT_PORT=6333
export RAG_INGEST_WORKERS=2
export RAG_EMBEDDING_PROVIDER=local
export RAG_EMBEDDING_MODEL=BAAI/bge-base-en-v1.5
export RAG_EMBEDDING_DEVICE=cpu
export RAG_EMBEDDING_DIMENSION=768
export RAG_GENERATION_ENABLED=false
```

## 4. Seed A Project Config

The gateway resolves adapters from project config. Add a website project before calling search or ingest:

```bash
python - <<'PY'
import asyncio
import os
from pathlib import Path

from rag_server.config import SQLiteProjectConfigRepository
from rag_server.core import BaseProjectConfig

async def main():
    repo = SQLiteProjectConfigRepository(Path(os.environ["RAG_CONFIG_DB_PATH"]))
    await repo.initialize()
    await repo.upsert_project(
        BaseProjectConfig(
            project_id="demo",
            project_type="website",
            active_embedding_version="v1",
            embedding_model="BAAI/bge-base-en-v1.5",
            reranker_model="none",
            retrieval_config={"candidate_count": 20, "top_k": 5},
        )
    )

asyncio.run(main())
PY
```

## 5. Start The Server

```bash
python -m rag_server.app
```

On first start, the embedding model may take time to download/load.

## 6. Ingest A Small Document

In another shell with the same environment activated:

```bash
python - <<'PY'
import asyncio
import grpc

from rag_server.grpc import rag_service_pb2, rag_service_pb2_grpc

async def main():
    async with grpc.aio.insecure_channel("localhost:50051") as channel:
        client = rag_service_pb2_grpc.RagServiceStub(channel)
        response = await client.Ingest(
            rag_service_pb2.IngestRequest(
                project_id="demo",
                user_id="user_1",
                # kb_id may be omitted; blank means "default".
                doc_id="hello_doc",
                source_uri="memory://hello_doc",
                content_type="text/plain",
                metadata={
                    "raw_text": "Hello world.\n\nThis service indexes chunks for retrieval.",
                },
            )
        )
        print(response)

asyncio.run(main())
PY
```

Save the returned `job_id`.

## 7. Check Ingest Status

```bash
python - <<'PY'
import asyncio
import grpc

from rag_server.grpc import rag_service_pb2, rag_service_pb2_grpc

JOB_ID = "replace-with-job-id"

async def main():
    async with grpc.aio.insecure_channel("localhost:50051") as channel:
        client = rag_service_pb2_grpc.RagServiceStub(channel)
        response = await client.GetIngestJobStatus(
            rag_service_pb2.GetIngestJobStatusRequest(job_id=JOB_ID)
        )
        print(response)

asyncio.run(main())
PY
```

Expected status after processing:

```text
completed
```

## 8. Search

```bash
python - <<'PY'
import asyncio
import grpc

from rag_server.grpc import rag_service_pb2, rag_service_pb2_grpc

async def main():
    async with grpc.aio.insecure_channel("localhost:50051") as channel:
        client = rag_service_pb2_grpc.RagServiceStub(channel)
        response = await client.Search(
            rag_service_pb2.SearchRequest(
                project_id="demo",
                user_id="user_1",
                query="What does the service index?",
                include_shared=True,
            )
        )
        print(response)

asyncio.run(main())
PY
```

Search retrieves chunks from Qdrant using vector similarity plus server-built filters:

```text
project_id = demo
user_id IN [user_1, __shared__]
```

No KB filter is added unless `kb_ids` is provided.

## 9. Optional Generation

Generation is disabled by default. To enable the OpenRouter client:

```bash
export RAG_GENERATION_ENABLED=true
```

Restart the server.

Generation requests still require a request-scoped OpenRouter key:

```text
GenerateRequest.openrouter_api_key
```

Do not put provider keys in environment variables unless you are building your own wrapper outside this service. The service is designed to use user/request-provided keys.

## Troubleshooting

### `ModuleNotFoundError: grpc` or Missing Runtime Dependencies

Install dependencies:

```bash
python -m pip install -e ".[dev]"
```

Make sure you run this in the same environment that starts the server. For this workspace:

```bash
source /home/bruce/miniconda3/etc/profile.d/conda.sh
conda activate evo
python -m pip install -e ".[dev]"
```

### Qdrant Connection Errors

Make sure Qdrant is running:

```bash
curl http://localhost:6333/collections
```

### Ingest Fails With Embedding Dimension Error

Set `RAG_EMBEDDING_DIMENSION` to match the selected embedding model. The local default is 768.

### Search Returns No Results

Check:

- project config exists for `project_id`
- ingest job completed
- Qdrant is running
- `user_id` matches the ingested document
- `include_shared` is true only if you expect shared records
- `kb_ids` is omitted unless you intentionally used a custom KB
