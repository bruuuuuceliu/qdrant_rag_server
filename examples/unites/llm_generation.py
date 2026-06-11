"""Minimal LLM generation showcase.

Setup:
1. Install dependencies: ``python -m pip install -e .``
2. Set ``RAG_GENERATION_API_KEY`` in ``examples/unites/.env``.
3. Run: ``python -m examples.unites.llm_generation``
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from retrieval_service.llm import LLMProviderFactory  # noqa: E402

load_dotenv(Path(__file__).with_name(".env"))


async def main() -> None:
    api_key = os.getenv("RAG_GENERATION_API_KEY", "")
    if not api_key:
        print("Set RAG_GENERATION_API_KEY in examples/unites/.env")
        return

    llm = LLMProviderFactory.create(
        os.getenv("RAG_GENERATION_PROVIDER", "openrouter"),
        api_key=api_key,
        base_url=os.getenv(
            "RAG_GENERATION_BASE_URL",
            "https://openrouter.ai/api/v1/chat/completions",
        ),
        default_model=os.getenv("RAG_GENERATION_MODEL", "openai/gpt-4o-mini"),
        default_max_tokens=int(os.getenv("RAG_GENERATION_MAX_TOKENS", "256")),
        default_temperature=float(os.getenv("RAG_GENERATION_TEMPERATURE", "0.2")),
    )
    await llm.initialize()
    try:
        response = await llm.generate_response(
            messages=[
                {
                    "role": "user",
                    "content": "Explain retrieval augmented generation in one sentence.",
                }
            ]
        )
        print(response)
    finally:
        await llm.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
