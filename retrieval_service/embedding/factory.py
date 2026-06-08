"""Embedding provider factory.

Maps stable provider names to concrete implementations. Add new
providers by registering them here.
"""

from __future__ import annotations

from retrieval_service.embedding.protocols import EmbeddingProvider

OPENROUTER_EMBEDDINGS_URL = "https://openrouter.ai/api/v1/embeddings"


class EmbeddingProviderFactory:
    """Creates configured embedding providers by stable provider name."""

    @staticmethod
    def create(
        provider: str,
        *,
        model_name: str,
        device: str = "cpu",
        api_key: str = "",
        base_url: str = OPENROUTER_EMBEDDINGS_URL,
    ) -> EmbeddingProvider:
        from retrieval_service.embedding.local import LocalSentenceTransformerEmbedding
        from retrieval_service.embedding.openai_compatible import OpenAICompatibleEmbedding
        from retrieval_service.embedding.openrouter import OpenRouterEmbedding

        normalized = provider.strip().lower()
        if normalized in {"local", "sentence_transformer", "sentence-transformer"}:
            return LocalSentenceTransformerEmbedding(model_name=model_name, device=device)
        if normalized == "openrouter":
            return OpenRouterEmbedding(
                api_key=api_key,
                model_name=model_name,
                base_url=base_url,
            )
        if normalized in {"openai", "remote", "openai_compatible"}:
            return OpenAICompatibleEmbedding(
                api_key=api_key,
                model_name=model_name,
                base_url=base_url,
            )
        raise ValueError(
            "RAG_EMBEDDING_PROVIDER must be one of: "
            "local, sentence_transformer, openrouter, openai, remote, openai_compatible"
        )
