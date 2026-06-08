"""OpenRouter embedding provider."""

from __future__ import annotations

from retrieval_service.embedding.openai_compatible import OpenAICompatibleEmbedding
from retrieval_service.embedding.utils import OPENROUTER_EMBEDDINGS_URL


class OpenRouterEmbedding(OpenAICompatibleEmbedding):
    """OpenRouter embeddings client using the OpenAI-compatible endpoint."""

    def __init__(
        self,
        *,
        api_key: str,
        model_name: str,
        base_url: str = OPENROUTER_EMBEDDINGS_URL,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not api_key.startswith("sk-or-"):
            raise ValueError("OpenRouter embedding api key must start with sk-or-")
        super().__init__(
            api_key=api_key,
            model_name=model_name,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
        )
