#!/usr/bin/env python3
"""Example save-and-retrieve scenario.

Run this while the gRPC server is up:

    python -m server.app
    python test_1.py
"""

from __future__ import annotations

import asyncio
import os

from test_client import RagServiceTestClient


POST = {
    "doc_id": "test_1_qdrant_note",
    "source_uri": "memory://test_1_qdrant_note",
    "raw_text": (
        "Qdrant stores vectors and payload metadata for semantic search.\n\n"
        "The retrieval service saves text as chunks, embeds those chunks, "
        "and later searches them with project and user filters."
    ),
    "query": "What does Qdrant store for semantic search?",
    "topic": "qdrant",
}


async def main() -> None:
    client = RagServiceTestClient(
        target=os.getenv("RAG_GRPC_TARGET", "localhost:50051"),
        project_id=os.getenv("RAG_TEST_PROJECT_ID", "demo"),
        user_id=os.getenv("RAG_TEST_USER_ID", "user_1"),
        default_kb_id=os.getenv("RAG_TEST_KB_ID", "default"),
    )

    async with client:
        result = await client.save_and_retrieve(POST)

    print(f"ingest job: {result.job_id}")
    print(f"job status: {result.job_status.status}")
    print(f"cache hit: {result.search_response.cache_hit}")
    for chunk in result.search_response.chunks:
        print(f"{chunk.doc_id} score={chunk.score:.3f}: {chunk.text}")


if __name__ == "__main__":
    asyncio.run(main())

