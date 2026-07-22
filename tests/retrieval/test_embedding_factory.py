"""Embedding provider factory tests."""

from __future__ import annotations

import pytest

from retrieval_service.embedding import DeterministicHashEmbedding, EmbeddingProviderFactory


@pytest.mark.asyncio
async def test_factory_creates_dimensioned_deterministic_embedding() -> None:
    provider = EmbeddingProviderFactory.create(
        "deterministic",
        model_name="deterministic-hash",
        dimension=16,
    )

    assert isinstance(provider, DeterministicHashEmbedding)
    await provider.initialize()
    vector = await provider.encode("Qdrant stores semantic retrieval vectors.")

    assert len(vector) == 16
    assert any(value != 0.0 for value in vector)


@pytest.mark.asyncio
async def test_deterministic_embedding_scores_shared_tokens_higher() -> None:
    provider = await DeterministicHashEmbedding(dimension=64).initialize()

    query = await provider.encode("semantic retrieval")
    related = await provider.encode("Qdrant stores vectors for semantic retrieval.")
    unrelated = await provider.encode("bananas invoices calendars")

    assert _dot(query, related) > _dot(query, unrelated)


def test_factory_rejects_unknown_embedding_provider() -> None:
    with pytest.raises(ValueError, match="RAG_EMBEDDING_PROVIDER"):
        EmbeddingProviderFactory.create("unknown", model_name="model")


def _dot(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))
