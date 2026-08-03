"""Embedding provider factory tests."""

from __future__ import annotations

import pytest

from retrieval_service.embedding import (
    DeterministicHashEmbedding,
    EmbeddingProviderFactory,
    LocalSentenceTransformerEmbedding,
)


class _FakeSentenceModel:
    """FAKE model for unit tests — NEVER load the real bge checkpoint here."""

    def __init__(self, dimension: int) -> None:
        self._dimension = dimension

    def get_sentence_embedding_dimension(self) -> int:
        return self._dimension


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


@pytest.mark.asyncio
async def test_local_embedding_rejects_dimension_mismatch(monkeypatch) -> None:
    monkeypatch.setattr(
        "retrieval_service.embedding.local._load_model",
        lambda model_name, device: _FakeSentenceModel(384),
    )
    provider = LocalSentenceTransformerEmbedding(
        model_name="fake-bge",
        dimension=768,
    )
    with pytest.raises(ValueError, match=r"produces 384-dim vectors"):
        await provider.initialize()


@pytest.mark.asyncio
async def test_local_embedding_accepts_matching_dimension(monkeypatch) -> None:
    monkeypatch.setattr(
        "retrieval_service.embedding.local._load_model",
        lambda model_name, device: _FakeSentenceModel(768),
    )
    provider = LocalSentenceTransformerEmbedding(
        model_name="fake-bge",
        dimension=768,
    )
    result = await provider.initialize()
    assert result is provider
    await provider.shutdown()


@pytest.mark.asyncio
async def test_factory_passes_dimension_to_local_provider(monkeypatch) -> None:
    monkeypatch.setattr(
        "retrieval_service.embedding.local._load_model",
        lambda model_name, device: _FakeSentenceModel(768),
    )
    provider = EmbeddingProviderFactory.create(
        "local",
        model_name="fake-bge",
        dimension=768,
    )
    assert isinstance(provider, LocalSentenceTransformerEmbedding)
    await provider.initialize()
    await provider.shutdown()


def _dot(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))
