# LLM And Embedding Provider Design

## Status

This is the first provider-oriented design pass. The current runtime still uses
local sentence-transformer embeddings, OpenAI-compatible remote embeddings, and
OpenRouter generation, but these now sit behind stable provider contracts.

This document is intentionally implementation-shaped. It should be possible to
turn the protocols and pseudocode here into code without revisiting the whole
architecture.

## Goals

- Keep retrieval usable without an LLM.
- Keep embedding providers replaceable without changing the engine.
- Let query and ingest embeddings diverge later through a task hint.
- Keep generation provider keys out of stored payloads, logs, and cache keys.
- Leave room for LLM-assisted ingestion, reranking, and answer generation.

## Non-Goals

- Do not make answer generation required for search.
- Do not store provider API keys in project config, Qdrant payloads, logs, or
  cache records.
- Do not let the engine branch on concrete providers such as OpenRouter,
  OpenAI, Ollama, or sentence-transformers.
- Do not put LLM extraction logic directly in transport code.

## Core Types

```python
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

EmbeddingTask = Literal["ingest", "search", "update"]
LlmTask = Literal["extract", "generate", "rerank", "classify"]

ChatRole = Literal["system", "user", "assistant", "tool"]

@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: ChatRole
    content: str
    name: str | None = None

@dataclass(frozen=True, slots=True)
class EmbeddingRequest:
    texts: tuple[str, ...]
    task: EmbeddingTask
    model: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    vectors: list[list[float]]
    model: str
    dimension: int

@dataclass(frozen=True, slots=True)
class LlmRequest:
    messages: tuple[ChatMessage, ...]
    task: LlmTask
    api_key: str | None = None
    model: str | None = None
    max_tokens: int = 1024
    temperature: float = 0.7
    response_format: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True, slots=True)
class LlmResult:
    content: str
    model: str
    provider: str
    raw_usage: dict[str, Any] = field(default_factory=dict)
```

The first code pass uses simpler method signatures, but these request/result
objects are the target shape once there are more than two providers.

## Embedding Provider Interface

Embeddings implement:

```python
class EmbeddingProvider(Protocol):
    async def initialize(self) -> "EmbeddingProvider":
        """Open clients, load local models, and return self."""

    async def encode(
        self,
        text: str,
        *,
        task: EmbeddingTask = "search",
    ) -> list[float]:
        """Embed one text string."""

    async def encode_batch(
        self,
        texts: list[str],
        *,
        task: EmbeddingTask = "ingest",
    ) -> list[list[float]]:
        """Embed many text strings, preserving input order."""

    async def shutdown(self) -> None:
        """Close HTTP clients or model executors."""
```

The task hint is currently advisory. Providers may ignore it, but it gives
future providers a clean place for query/document prefixes or asymmetric models.

Expected behavior:

- `encode_batch([])` returns `[]`.
- Output vector count must equal input text count.
- Every vector must have the configured collection dimension.
- Provider errors should redact API keys.
- Local CPU/GPU inference must not block the event loop; use an executor.
- Remote providers should reuse an async HTTP client.

Provider pseudocode:

```python
class LocalSentenceTransformerEmbedding:
    async def initialize(self):
        self.executor = ThreadPoolExecutor(max_workers=self.max_workers)
        self.model = await loop.run_in_executor(
            self.executor,
            SentenceTransformer,
            self.model_name,
            self.device,
        )
        return self

    async def encode(self, text, *, task="search"):
        vectors = await self.encode_batch([text], task=task)
        return vectors[0]

    async def encode_batch(self, texts, *, task="ingest"):
        prepared = [self._prepare_text(text, task) for text in texts]
        return await loop.run_in_executor(
            self.executor,
            self._model_encode,
            prepared,
        )

    def _prepare_text(self, text, task):
        if self.query_prefix and task == "search":
            return f"{self.query_prefix}{text}"
        if self.document_prefix and task in {"ingest", "update"}:
            return f"{self.document_prefix}{text}"
        return text
```

```python
class OpenAICompatibleEmbedding:
    async def initialize(self):
        self.client = httpx.AsyncClient(timeout=self.timeout)
        return self

    async def encode_batch(self, texts, *, task="ingest"):
        if not texts:
            return []

        payload = {
            "model": self.model_name,
            "input": [self._prepare_text(text, task) for text in texts],
        }
        if self.dimension_is_provider_configurable:
            payload["dimensions"] = self.dimension

        response = await self.client.post(
            self.base_url,
            headers=self._auth_headers(),
            json=payload,
        )
        data = self._parse_or_raise(response)
        vectors = [item["embedding"] for item in sorted(data["data"], key=index)]
        self._validate_vectors(vectors, expected_count=len(texts))
        return vectors
```

## LLM Provider Interface

LLMs implement:

```python
class LLMProvider(Protocol):
    async def generate_response(
        self,
        *,
        messages: list[dict[str, str]],
        api_key: str | None = None,
        model: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        """Return generated text for chat messages."""
```

OpenRouter remains the first implementation. The interface intentionally uses
chat messages rather than raw prompts so future ingestion extraction, reranking,
and structured generation can share the same provider surface.

Expected behavior:

- `messages` is the canonical input shape. Raw prompts should be a compatibility
  wrapper only.
- Request-level `api_key` overrides configured `api_key`.
- Provider default model is used when `model is None`.
- Provider errors redact keys.
- JSON response format is optional and provider-specific.
- The provider should not know about Qdrant, chunks, or project adapters.

Provider pseudocode:

```python
class OpenRouterLLM:
    async def generate_response(
        self,
        *,
        messages,
        api_key=None,
        model=None,
        max_tokens=1024,
        temperature=0.7,
        response_format=None,
    ):
        selected_key = api_key or self.api_key
        selected_model = model or self.default_model
        self._validate_key(selected_key)

        payload = {
            "model": selected_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if response_format:
            payload["response_format"] = response_format

        response = await self.http.post(
            self.base_url,
            headers=self._headers(selected_key),
            json=payload,
        )
        if not response.is_success:
            raise LLMProviderError(self._redact(response.text))

        return response.json()["choices"][0]["message"]["content"]

    async def generate(self, *, prompt, api_key, model=None, **kwargs):
        return await self.generate_response(
            messages=[{"role": "user", "content": prompt}],
            api_key=api_key,
            model=model,
            **kwargs,
        )
```

## Factories

Factories are the only places that map provider names to concrete classes.

```python
class EmbeddingProviderFactory:
    @staticmethod
    def create(
        provider: str,
        *,
        model_name: str,
        device: str = "cpu",
        api_key: str = "",
        base_url: str = DEFAULT_EMBEDDING_URL,
    ) -> EmbeddingProvider:
        match provider.strip().lower():
            case "local" | "sentence_transformer":
                return LocalSentenceTransformerEmbedding(
                    model_name=model_name,
                    device=device,
                )
            case "openrouter" | "openai" | "remote" | "openai_compatible":
                return OpenAICompatibleEmbedding(
                    api_key=api_key,
                    model_name=model_name,
                    base_url=base_url,
                )
            case _:
                raise ValueError(f"unsupported embedding provider: {provider}")
```

```python
class LLMProviderFactory:
    @staticmethod
    def create(
        provider: str,
        *,
        base_url: str,
        api_key: str = "",
        default_model: str,
    ) -> LLMProvider:
        match provider.strip().lower():
            case "openrouter" | "openai_compatible":
                return OpenRouterLLM(
                    base_url=base_url,
                    api_key=api_key,
                    default_model=default_model,
                )
            case _:
                raise ValueError(f"unsupported generation provider: {provider}")
```

## Configuration Definitions

Application-level settings:

```python
@dataclass(frozen=True, slots=True)
class EmbeddingSettings:
    provider: str
    model: str
    device: str
    api_key: str
    base_url: str
    dimension: int
    query_prefix: str = ""
    document_prefix: str = ""

@dataclass(frozen=True, slots=True)
class GenerationSettings:
    enabled: bool
    provider: str
    model: str
    api_key: str
    base_url: str
    max_tokens: int
    temperature: float
```

Project-level retrieval config should eventually add provider overrides:

```python
@dataclass(frozen=True, slots=True)
class ProjectRetrievalConfig:
    top_k: int = 5
    candidate_count: int = 20
    enabled_retrievers: tuple[str, ...] = ("dense",)
    reranker: str | None = None
    embedding_version: str = "v1"
    embedding_model: str = ""
    dense_weight: float = 1.0
    sparse_weight: float = 0.0
```

## Runtime Roles

- Search uses embeddings and vector/sparse retrieval. It should not require an
  LLM.
- Ingest uses embeddings now. A future `infer=True` path may use an LLM to
  extract normalized facts before embedding.
- Generation is optional and request-scoped. The caller still supplies the
  OpenRouter key for hosted generation.
- Reranking can be either model-based or LLM-based later, behind the reranker
  service boundary.

## Search Flow

Current dense-only search:

```python
async def search(plan: SearchPlan) -> SearchResult:
    cache_key = make_search_cache_key(plan)
    cached = await tier1_cache.get(project_id, cache_key)
    if cached:
        return cached

    query_vector = await embedding_provider.encode(
        plan.request.query,
        task="search",
    )

    qdrant_filter = build_qdrant_filter(plan.retrieval_filter)
    hits = await qdrant_store.search(
        collection_name=plan.config.collection_name,
        query_vector=query_vector,
        query_filter=qdrant_filter,
        limit=plan.config.retrieval_config["candidate_count"],
    )

    candidates = format_hits(hits)
    if reranker:
        candidates = await reranker.rerank(plan.request.query, candidates)

    result = SearchResult(chunks=candidates[:top_k])
    await tier1_cache.set(project_id, cache_key, result)
    return result
```

Future hybrid search:

```python
async def search(plan):
    retrievers = retriever_factory.enabled(plan.config.retrieval_config)

    retrieval_tasks = [
        retriever.retrieve(
            query=plan.request.query,
            filter=plan.retrieval_filter,
            config=plan.config,
        )
        for retriever in retrievers
    ]
    result_sets = await asyncio.gather(*retrieval_tasks)

    merged = merge_candidates(
        result_sets,
        weights={"dense": 1.0, "sparse": 0.4, "metadata": 0.2},
    )
    if reranker:
        merged = await reranker.rerank(plan.request.query, merged)

    return SearchResult(chunks=merged[:top_k])
```

## Ingest Flow

Current ingest:

```python
async def run_ingest(plan):
    document = await adapter.parse_document(plan.request)
    chunks = await adapter.build_chunks(document)
    texts = [chunk.text for chunk in chunks]

    vectors = await embedding_provider.encode_batch(
        texts,
        task="ingest",
    )

    payloads = [await adapter.build_payload(chunk) for chunk in chunks]
    await vector_store.upsert(
        collection_name=plan.config.collection_name,
        vectors=vectors,
        payloads=payloads,
    )
```

Future LLM-assisted extraction should be a service before chunking or before
payload construction, not custom logic in `RagEngine`:

```python
class IngestExtractionService:
    def __init__(self, *, llm: LLMProvider, prompt_builder: PromptBuilder):
        self.llm = llm
        self.prompt_builder = prompt_builder

    async def extract(self, request: ExtractionRequest) -> ExtractionResult:
        messages = self.prompt_builder.build_extraction_messages(
            raw_text=request.raw_text,
            source_uri=request.source_uri,
            existing_context=request.existing_context,
            data_type=request.data_type,
        )
        content = await self.llm.generate_response(
            messages=messages,
            api_key=request.provider_key,
            model=request.model,
            response_format={"type": "json_object"},
            temperature=0.0,
        )
        return self._parse_extraction_json(content)
```

Extraction result target:

```python
@dataclass(frozen=True, slots=True)
class ExtractedRecord:
    text: str
    data_type: str
    source_span: tuple[int, int] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True, slots=True)
class ExtractionResult:
    records: tuple[ExtractedRecord, ...]
    raw_response: str
```

## Generation Flow

Answer generation should remain optional and cache-aware:

```python
async def generate(project_id, user_id, query, chunks, provider_key, model=None):
    if llm_provider is None:
        raise GenerationUnavailableError("generation is disabled")

    cache_key = make_response_cache_key(
        project_id=project_id,
        user_id=user_id,
        query=query,
        chunks=chunks,
        provider=llm_provider.name,
        model=model or llm_provider.default_model,
    )
    cached = await tier2_cache.get(project_id, user_id, cache_key)
    if cached:
        return GenerateResult(response=cached, cache_hit=True)

    messages = prompt_builder.build_answer_messages(query=query, chunks=chunks)
    response = await llm_provider.generate_response(
        messages=messages,
        api_key=provider_key,
        model=model,
    )
    await tier2_cache.set(project_id, user_id, cache_key, response)
    return GenerateResult(response=response, cache_hit=False)
```

Prompt builder interface:

```python
class PromptBuilder(Protocol):
    def build_answer_messages(
        self,
        *,
        query: str,
        chunks: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        ...

    def build_extraction_messages(
        self,
        *,
        raw_text: str,
        source_uri: str,
        existing_context: list[dict[str, Any]],
        data_type: str,
    ) -> list[dict[str, str]]:
        ...
```

## Reranking Flow

Rerankers should share a candidate contract:

```python
@dataclass(frozen=True, slots=True)
class RetrievalCandidate:
    chunk_id: str
    text: str
    score: float
    payload: dict[str, Any]
    source: str = "dense"
    score_details: dict[str, float] = field(default_factory=dict)

class Reranker(Protocol):
    async def rerank(
        self,
        query: str,
        candidates: list[RetrievalCandidate],
        *,
        top_k: int,
    ) -> list[RetrievalCandidate]:
        ...
```

LLM reranker pseudocode:

```python
class LlmReranker:
    async def rerank(self, query, candidates, *, top_k):
        scored = []
        for candidate in candidates[:self.max_candidates]:
            response = await self.llm.generate_response(
                messages=[
                    {"role": "system", "content": self.scoring_instructions},
                    {"role": "user", "content": format_pair(query, candidate.text)},
                ],
                temperature=0.0,
                max_tokens=16,
            )
            rerank_score = parse_float_or_default(response, default=0.5)
            scored.append(replace(candidate, score=rerank_score))

        return sorted(scored, key=lambda item: item.score, reverse=True)[:top_k]
```

## Error And Security Rules

- Redact `sk-*`, `sk-or-*`, bearer tokens, and provider-specific key patterns.
- Never include API keys in cache keys; include provider and model names instead.
- Request-scoped keys may be passed only in memory to provider calls.
- LLM output must be treated as untrusted data and parsed defensively.
- If structured JSON parsing fails, return a controlled error or empty extraction
  result rather than storing raw hallucinated text.
- Provider construction errors should fail app startup only when the provider is
  enabled.

## Test Contracts

Provider conformance tests:

```python
async def test_embedding_provider_preserves_batch_order(provider):
    vectors = await provider.encode_batch(["a", "b"], task="ingest")
    assert len(vectors) == 2
    assert vectors[0] != vectors[1]

async def test_embedding_provider_empty_batch(provider):
    assert await provider.encode_batch([], task="ingest") == []

async def test_llm_provider_uses_default_model(http_mock):
    llm = OpenRouterLLM(default_model="provider-default")
    await llm.generate_response(
        messages=[{"role": "user", "content": "hello"}],
        api_key="sk-or-test",
    )
    assert http_mock.last_json["model"] == "provider-default"

async def test_llm_provider_redacts_error(http_mock):
    http_mock.fail(text="bad key sk-or-secret")
    with pytest.raises(LLMProviderError) as exc:
        await llm.generate_response(messages=[...], api_key="sk-or-secret")
    assert "sk-or-secret" not in str(exc.value)
```

Engine integration tests:

```python
async def test_search_calls_embedding_with_search_task(engine, plan):
    await engine.search(plan)
    embedding_provider.encode.assert_awaited_once_with(
        plan.request.query,
        task="search",
    )

async def test_ingest_calls_embedding_with_ingest_task(engine, plan):
    await engine._run_ingest("job", plan)
    embedding_provider.encode_batch.assert_awaited_once_with(
        ["chunk text"],
        task="ingest",
    )
```

## Next Steps

1. Move `server.app._build_embedding_provider()` onto `EmbeddingProviderFactory`
   once current app-wiring tests are updated.
2. Add an LLM extraction service for ingest instead of putting extraction logic
   in `RagEngine`.
3. Add a retriever framework that can merge dense and BM25 sparse candidates.
4. Include generation model/provider settings in response cache keys.
5. Add provider conformance tests for local embeddings, remote embeddings, and
   OpenRouter chat generation.
