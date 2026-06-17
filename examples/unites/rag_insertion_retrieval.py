"""Manager-service RAG insertion and retrieval showcase.

Uses the ManagerService facade with a local queue broker and project client —
the same composition the manager app boots. This is the recommended way to
interact with the platform programmatically.

Setup:
1. Install dependencies: ``python -m pip install -e .``
2. Start Qdrant: ``docker run --rm -p 6333:6333 -p 6334:6334 qdrant/qdrant``
3. Set ``RAG_EMBEDDING_API_KEY`` in ``examples/unites/.env``.
   ``RAG_GENERATION_API_KEY`` is used as a fallback.
4. Confirm ``RAG_QDRANT_HOST``, ``RAG_QDRANT_PORT``, and
   ``RAG_EMBEDDING_DIMENSION`` match your local Qdrant/model settings.
5. Run: ``python -m examples.unites.rag_insertion_retrieval``

The showcase:
- Seeds a project config
- Creates ManagerService with an ingest queue and project-document client
- Ingests documents through the manager boundary (queue → consumer → engine)
- Searches through the manager boundary
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from manager_service import ManagerService, ProjectDocumentClient  # noqa: E402
from manager_service.routing import ManagerRouter  # noqa: E402
from project_service.adapters.website import WebsiteProjectAdapter  # noqa: E402
from project_service.client import LocalProjectServiceClient  # noqa: E402
from project_service.config import SQLiteProjectConfigRepository  # noqa: E402
from project_service.gateway import (  # noqa: E402
    AsyncConcurrencyLimiter,
    IngestRequest,
    RagGateway,
    SearchRequest,
)
from project_service.rag import RagEngine  # noqa: E402
from project_service.schemas import ProjectConfig  # noqa: E402
from retrieval_service.embedding import EmbeddingProviderFactory  # noqa: E402
from retrieval_service.services.vector_store import QdrantStore  # noqa: E402
from shared.queue import LocalQueueBroker  # noqa: E402

load_dotenv(Path(__file__).with_name(".env"))


async def main() -> None:
    project_id = os.getenv("RAG_SHOWCASE_PROJECT_ID", "unite_project")
    user_id = os.getenv("RAG_SHOWCASE_USER_ID", "user_a")
    kb_id = os.getenv("RAG_SHOWCASE_KB_ID", "demo")
    embedding_model = os.getenv("RAG_EMBEDDING_MODEL", "openai/text-embedding-3-small")
    embedding_dimension = int(os.getenv("RAG_EMBEDDING_DIMENSION", "1536"))
    api_key = os.getenv("RAG_EMBEDDING_API_KEY") or os.getenv(
        "RAG_GENERATION_API_KEY", ""
    )
    if not api_key:
        print("Set RAG_EMBEDDING_API_KEY or RAG_GENERATION_API_KEY in examples/unites/.env")
        return

    # --- Bootstrap: seed config, build service components -------------------

    config_db = Path("/tmp/qdrant_rag_unite_config.db")

    config_repo = SQLiteProjectConfigRepository(config_db)
    await config_repo.initialize()
    await config_repo.upsert_project(
        ProjectConfig(
            project_id=project_id,
            project_type="website",
            active_embedding_version="v1",
            embedding_model=embedding_model,
            reranker_model="bge-reranker-base",
            retrieval_config={"top_k": 2, "candidate_count": 2},
        )
    )
    print(f"Seeded project config for {project_id}")

    adapter = WebsiteProjectAdapter(config_repo=config_repo)

    embedding = EmbeddingProviderFactory.create(
        "openrouter",
        model_name=embedding_model,
        api_key=api_key,
        base_url=os.getenv(
            "RAG_EMBEDDING_BASE_URL",
            "https://openrouter.ai/api/v1/embeddings",
        ),
    )
    await embedding.initialize()

    qdrant_store = QdrantStore(
        url=os.getenv("RAG_QDRANT_URL") or None,
        host=os.getenv("RAG_QDRANT_HOST", "localhost"),
        port=int(os.getenv("RAG_QDRANT_PORT", "6333")),
        default_vector_size=embedding_dimension,
    )

    gateway = RagGateway(
        adapter_resolver=_FakeResolver(adapter),
        concurrency_limiter=AsyncConcurrencyLimiter(
            max_per_project=10,
            max_per_user=5,
        ),
    )

    engine = RagEngine(
        embedding_provider=embedding,
        qdrant_store=qdrant_store,
        ingest_worker_count=1,
    )

    # --- Build the manager boundary -----------------------------------------

    project_client: ProjectDocumentClient = LocalProjectServiceClient(
        gateway=gateway,
        engine=engine,
    )

    broker = LocalQueueBroker(maxsize=10)
    manager = ManagerService(
        project_documents=project_client,
        ingest_queue=broker,
        ingest_topic="ingestion.requests",
        ingest_response_timeout=30.0,
        router=ManagerRouter(ingest_topic="ingestion.requests"),
    )

    # Start a tiny ingestion consumer in the background
    from ingestion_service.server.consumer import IngestionRequestConsumer
    consumer = IngestionRequestConsumer(
        queue=broker,
        project_documents=project_client,
        topic="ingestion.requests",
    )
    consumer.start()
    await asyncio.sleep(0.05)  # let consumer spin up

    try:
        # --- Ingest through the manager -------------------------------------
        for doc_id, text in {
            "doc_qdrant": "Qdrant stores vectors for semantic search.",
            "doc_rag": "RAG retrieves context before generation.",
        }.items():
            result = await manager.ingest(
                IngestRequest(
                    project_id=project_id,
                    user_id=user_id,
                    kb_id=kb_id,
                    doc_id=doc_id,
                    source_uri=f"https://example.com/{doc_id}",
                    content_type="text/html",
                    raw_text=text,
                )
            )
            print(f"Ingested {doc_id} → job_id={result.job_id} status={result.status}")

        # Wait for background processing to complete
        await asyncio.sleep(0.2)

        # --- Search through the manager -------------------------------------
        search_result = await manager.search(
            SearchRequest(
                project_id=project_id,
                user_id=user_id,
                query="How does RAG retrieve context?",
                kb_ids=(kb_id,),
            )
        )
        print("\nSearch results:")
        for chunk in search_result.chunks:
            print(f"  {chunk['doc_id']} score={chunk['score']:.3f}: {chunk['text']}")

    finally:
        await consumer.stop()
        await engine.shutdown()
        await embedding.shutdown()
        await qdrant_store.close()


class _FakeResolver:
    """Simple resolver returning the same adapter for the showcase."""

    def __init__(self, adapter: object) -> None:
        self._adapter = adapter

    async def resolve(self, project_id: str) -> object:
        del project_id
        return self._adapter


if __name__ == "__main__":
    asyncio.run(main())
