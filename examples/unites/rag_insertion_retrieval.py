"""Minimal RAG insertion and retrieval showcase.

Setup:
1. Install dependencies: ``python -m pip install -e .``
2. Start Qdrant: ``docker run --rm -p 6333:6333 -p 6334:6334 qdrant/qdrant``
3. Set ``RAG_EMBEDDING_API_KEY`` in ``examples/unites/.env``.
   ``RAG_GENERATION_API_KEY`` is used as a fallback.
4. Confirm ``RAG_QDRANT_HOST``, ``RAG_QDRANT_PORT``, and
   ``RAG_EMBEDDING_DIMENSION`` match your local Qdrant/model settings.
5. Run: ``python -m examples.unites.rag_insertion_retrieval``


http://localhost:6333/dashboard
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from project_service.adapters.website import (  # noqa: E402
    WebsiteProjectAdapter,
    WebsiteProjectConfig,
)
from project_service.gateway import (  # noqa: E402
    IngestPlan,
    IngestRequest,
    SearchPlan,
    SearchRequest,
)
from project_service.rag import RagEngine  # noqa: E402
from retrieval_service.embedding import EmbeddingProviderFactory  # noqa: E402
from retrieval_service.services.vector_store import QdrantStore  # noqa: E402

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

    adapter = WebsiteProjectAdapter()
    base_config = await adapter.get_config(project_id)
    config = WebsiteProjectConfig(
        project_id=base_config.project_id,
        project_type=base_config.project_type,
        active_embedding_version=base_config.active_embedding_version,
        embedding_model=embedding_model,
        reranker_model=base_config.reranker_model,
        domains=base_config.domains,
        crawl_rules=base_config.crawl_rules,
        sitemap_urls=base_config.sitemap_urls,
        default_locale=base_config.default_locale,
        retrieval_config={"top_k": 2, "candidate_count": 2},
    )

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
    engine = RagEngine(
        embedding_provider=embedding,
        qdrant_store=qdrant_store,
        ingest_worker_count=1,
    )

    try:
        for doc_id, text in {
            "doc_qdrant": "Qdrant stores vectors for semantic search.",
            "doc_rag": "RAG retrieves context before generation.",
        }.items():
            await engine.schedule_ingest(
                IngestPlan(
                    IngestRequest(
                        project_id,
                        user_id,
                        kb_id,
                        doc_id,
                        f"https://example.com/{doc_id}",
                        "text/html",
                        {"raw_text": text},
                    ),
                    adapter,
                    config,
                )
            )
        await engine._ingest_queue.join()

        search_request = SearchRequest(
            project_id,
            user_id,
            "How does RAG retrieve context?",
            (kb_id,),
        )
        scope = await adapter.build_query_scope(search_request)
        retrieval_filter = await adapter.build_retrieval_filter(scope)
        result = await engine.search(
            SearchPlan(
                search_request,
                adapter,
                config,
                scope,
                retrieval_filter,
            )
        )
        for chunk in result.chunks:
            print(f"{chunk['doc_id']} score={chunk['score']:.3f}: {chunk['text']}")
    finally:
        await engine.shutdown()
        await embedding.shutdown()
        await qdrant_store.close()


if __name__ == "__main__":
    asyncio.run(main())
