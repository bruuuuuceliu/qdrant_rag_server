"""Phase 8 tests: OpenRouter generation client and engine generation."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from retrieval_service.rag import (
    GenerationUnavailableError,
    RagEngine,
    GenerateResult,
    _make_response_cache_key,
)
from retrieval_service.llm import (
    LLMProviderFactory,
    OpenAICompatibleLLM,
    OpenRouterClient,
    OpenRouterClientError,
    OpenRouterLLM,
    _redact_key,
)


class RedactKeyTest(unittest.TestCase):
    def test_redacts_openrouter_key(self) -> None:
        text = "Authorization: Bearer sk-or-v1-abc123def456"
        result = _redact_key(text)
        self.assertNotIn("sk-or-v1-abc123def456", result)
        self.assertIn("[REDACTED]", result)

    def test_preserves_non_key_content(self) -> None:
        text = "User message with token sk-or-xyz for auth"
        result = _redact_key(text)
        self.assertIn("User message", result)
        self.assertIn("[REDACTED]", result)


class OpenRouterClientTest(unittest.IsolatedAsyncioTestCase):
    async def test_factory_creates_openrouter_provider(self) -> None:
        provider = LLMProviderFactory.create(
            "openrouter",
            base_url="https://example.test/chat/completions",
            default_model="provider-default-model",
        )

        self.assertIsInstance(provider, OpenRouterClient)
        self.assertIsInstance(provider, OpenRouterLLM)

    async def test_factory_creates_openai_compatible_provider(self) -> None:
        provider = LLMProviderFactory.create(
            "openai_compatible",
            base_url="https://example.test/chat/completions",
            api_key="sk-test",
            default_model="provider-default-model",
        )

        self.assertIsInstance(provider, OpenAICompatibleLLM)
        self.assertNotIsInstance(provider, OpenRouterLLM)

    async def test_rejects_empty_key(self) -> None:
        client = OpenRouterClient()
        with self.assertRaises(OpenRouterClientError):
            await client.generate(prompt="test", api_key="")

    async def test_rejects_invalid_key_prefix(self) -> None:
        client = OpenRouterClient()
        with self.assertRaises(OpenRouterClientError):
            await client.generate(prompt="test", api_key="pk-12345")

    async def test_redacts_key_from_response_text(self) -> None:
        text = "The key is sk-or-v1-deadbeef in the response"
        redacted = _redact_key(text)
        self.assertNotIn("sk-or-v1-deadbeef", redacted)

    async def test_successful_call_returns_content(self) -> None:
        client = OpenRouterClient(default_model="provider-default-model")
        http_client = MagicMock()
        http_client.aclose = AsyncMock()
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Hello from LLM"}}]
        }
        http_client.post = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value = http_client
            result = await client.generate(
                prompt="What is AI?",
                api_key="sk-or-v1-testkey123",
            )

        self.assertEqual(result, "Hello from LLM")
        posted_payload = http_client.post.call_args.kwargs["json"]
        self.assertEqual(posted_payload["model"], "provider-default-model")

    async def test_retries_on_429(self) -> None:
        client = OpenRouterClient(max_retries=2)
        http_client = MagicMock()
        http_client.aclose = AsyncMock()
        fail_response = MagicMock()
        fail_response.is_success = False
        fail_response.status_code = 429
        fail_response.text = "rate limited"

        success_response = MagicMock()
        success_response.is_success = True
        success_response.json.return_value = {
            "choices": [{"message": {"content": "Retried"}}]
        }

        mock_post = AsyncMock(side_effect=[fail_response, success_response])
        http_client.post = mock_post

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value = http_client
            result = await client.generate(
                prompt="test", api_key="sk-or-v1-testkey123"
            )

        self.assertEqual(result, "Retried")
        self.assertEqual(mock_post.call_count, 2)


class EngineGenerateTest(unittest.IsolatedAsyncioTestCase):
    async def test_generate_raises_when_generation_disabled(self) -> None:
        engine = RagEngine(
            embed_fn=AsyncMock(),
            qdrant_store=AsyncMock(),
        )

        with self.assertRaises(GenerationUnavailableError):
            await engine.generate(
                project_id="p1",
                user_id="u1",
                query="Hello",
                chunks=[],
                openrouter_key="sk-or-v1-key",
            )

    async def test_generate_cache_hit(self) -> None:
        tier2_cache = MagicMock()
        tier2_cache.get = AsyncMock(return_value="Cached response")

        engine = RagEngine(
            embed_fn=AsyncMock(),
            qdrant_store=AsyncMock(),
            tier2_cache=tier2_cache,
            openrouter_client=AsyncMock(),
        )

        result = await engine.generate(
            project_id="p1",
            user_id="u1",
            query="Hello",
            chunks=[{"chunk_id": "c1", "text": "context"}],
            openrouter_key="sk-or-v1-key",
        )

        self.assertTrue(result.cache_hit)
        self.assertEqual(result.response, "Cached response")

    async def test_generate_miss_calls_openrouter(self) -> None:
        tier2_cache = MagicMock()
        tier2_cache.get = AsyncMock(return_value=None)
        tier2_cache.set = AsyncMock()
        openrouter = MagicMock()
        openrouter.provider_name = "openrouter"
        openrouter.default_model = "test-model"
        openrouter.generate_response = AsyncMock(return_value="Generated response")

        engine = RagEngine(
            embed_fn=AsyncMock(),
            qdrant_store=AsyncMock(),
            tier2_cache=tier2_cache,
            openrouter_client=openrouter,
        )

        result = await engine.generate(
            project_id="p1",
            user_id="u1",
            query="Hello",
            chunks=[{"chunk_id": "c1", "text": "context"}],
            openrouter_key="sk-or-v1-key",
        )

        self.assertFalse(result.cache_hit)
        self.assertEqual(result.response, "Generated response")
        openrouter.generate_response.assert_awaited_once()
        tier2_cache.set.assert_called_once()


class ResponseCacheKeyTest(unittest.TestCase):
    def test_same_inputs_same_key(self) -> None:
        k1 = _make_response_cache_key("p1", "u1", "q", [{"chunk_id": "c1"}])
        k2 = _make_response_cache_key("p1", "u1", "q", [{"chunk_id": "c1"}])
        self.assertEqual(k1, k2)

    def test_different_chunks_different_key(self) -> None:
        k1 = _make_response_cache_key("p1", "u1", "q", [{"chunk_id": "c1"}])
        k2 = _make_response_cache_key("p1", "u1", "q", [{"chunk_id": "c2"}])
        self.assertNotEqual(k1, k2)

    def test_different_project_different_key(self) -> None:
        k1 = _make_response_cache_key("p1", "u1", "q", [{"chunk_id": "c1"}])
        k2 = _make_response_cache_key("p2", "u1", "q", [{"chunk_id": "c1"}])
        self.assertNotEqual(k1, k2)


if __name__ == "__main__":
    unittest.main()
