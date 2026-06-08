"""Minimal RAG insertion and retrieval showcase."""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from retrieval_service.adapters.website import WebsiteProjectAdapter, WebsiteProjectConfig
from retrieval_service.core.schemas import BaseChunkPayload
from retrieval_service.embedding import EmbeddingProviderFactory
from retrieval_service.gateway import IngestPlan, IngestRequest, SearchPlan, SearchRequest
from retrieval_service.rag import RagEngine

load_dotenv(Path(__file__).with_name(".env"))


@dataclass(frozen=True)
class Hit:
    payload: dict[str, Any]
    score: float


class MemoryStore:
    def __init__(self) -> None:
        self.points: list[tuple[list[float], dict[str, Any]]] = []

    async def upsert(
        self,
        collection_name: str,
        vectors: list[list[float]],
        payloads: list[BaseChunkPayload],
    ) -> None:
        self.points.extend(
            (vector, payload.to_qdrant_payload())
            for vector, payload in zip(vectors, payloads)
        )

    async def search(
        self,
        *,
        query_vector: list[float],
        query_filter: Any,
        limit: int,
        **_: Any,
    ) -> list[Hit]:
        hits = [Hit(payload, cosine(query_vector, vector)) for vector, payload in self.points]
        return sorted(hits, key=lambda hit: hit.score, reverse=True)[:limit]


async def main() -> None:
    project_id = os.getenv("RAG_SHOWCASE_PROJECT_ID", "unite_project")
    user_id = os.getenv("RAG_SHOWCASE_USER_ID", "user_a")
    kb_id = os.getenv("RAG_SHOWCASE_KB_ID", "demo")
    embedding_model = os.getenv("RAG_EMBEDDING_MODEL", "openai/text-embedding-3-small")
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

    engine = RagEngine(
        embedding_provider=embedding,
        qdrant_store=MemoryStore(),
        ingest_worker_count=1,
    )

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

    await engine.shutdown()
    await embedding.shutdown()


def cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


if __name__ == "__main__":
    asyncio.run(main())
