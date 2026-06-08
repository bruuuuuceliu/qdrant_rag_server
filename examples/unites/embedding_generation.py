"""Minimal embedding generation showcase."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from retrieval_service.embedding import EmbeddingProviderFactory

load_dotenv(Path(__file__).with_name(".env"))


async def main() -> None:
    provider = os.getenv("RAG_EMBEDDING_PROVIDER", "openrouter")
    api_key = os.getenv("RAG_EMBEDDING_API_KEY") or os.getenv(
        "RAG_GENERATION_API_KEY", ""
    )
    if provider == "openrouter" and not api_key:
        print("Set RAG_EMBEDDING_API_KEY or RAG_GENERATION_API_KEY in examples/unites/.env")
        return

    embedding = EmbeddingProviderFactory.create(
        provider,
        model_name=os.getenv("RAG_EMBEDDING_MODEL", "openai/text-embedding-3-small"),
        device=os.getenv("RAG_EMBEDDING_DEVICE", "cpu"),
        api_key=api_key,
        base_url=os.getenv(
            "RAG_EMBEDDING_BASE_URL",
            "https://openrouter.ai/api/v1/embeddings",
        ),
    )
    await embedding.initialize()
    try:
        vector = await embedding.encode("RAG retrieves context before generation.")
        print(f"dimension={len(vector)} preview={vector[:5]}")
    finally:
        await embedding.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
