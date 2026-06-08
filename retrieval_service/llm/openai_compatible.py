"""OpenAI-compatible LLM provider.

Works with OpenRouter, OpenAI, Ollama, and any OpenAI-compatible
chat completions API. API keys are request-scoped — never stored
in logs, cache entries, database records, or Qdrant payloads.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from retrieval_service.llm.protocols import ChatMessage, LLMProvider
from retrieval_service.llm.utils import LLMProviderError, _log_safe, _redact_key

logger = logging.getLogger(__name__)


class OpenAICompatibleLLM:
    """Asynchronous OpenAI-compatible chat completion client."""

    def __init__(
        self,
        *,
        base_url: str = "https://openrouter.ai/api/v1/chat/completions",
        api_key: str = "",
        default_model: str = "openai/gpt-4o-mini",
        default_max_tokens: int = 1024,
        default_temperature: float = 0.7,
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
    ) -> None:
        self._base_url = base_url
        self._api_key = api_key
        self._default_model = default_model
        self._default_max_tokens = default_max_tokens
        self._default_temperature = default_temperature
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        self._client: httpx.AsyncClient | None = None

    @property
    def provider_name(self) -> str:
        return "openai_compatible"

    @property
    def default_model(self) -> str:
        return self._default_model

    async def initialize(self) -> LLMProvider:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self

    async def generate_response(
        self,
        *,
        messages: list[ChatMessage],
        api_key: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        selected_key = api_key or self._api_key
        selected_model = model or self._default_model
        return await self._chat_completion(
            messages=messages,
            api_key=selected_key,
            model=selected_model,
            max_tokens=max_tokens if max_tokens is not None else self._default_max_tokens,
            temperature=temperature if temperature is not None else self._default_temperature,
            response_format=response_format,
        )

    async def generate(
        self,
        *,
        prompt: str,
        api_key: str,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        return await self.generate_response(
            messages=[{"role": "user", "content": prompt}],
            api_key=api_key,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    async def _chat_completion(
        self,
        *,
        messages: list[ChatMessage],
        api_key: str,
        model: str,
        max_tokens: int,
        temperature: float,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        if not api_key or not api_key.strip():
            raise LLMProviderError("API key is required for chat completion")

        if self._client is None:
            await self.initialize()

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if response_format is not None:
            payload["response_format"] = response_format

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        _log_safe("LLM request model=%s tokens=%d", model, max_tokens)

        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.post(
                    self._base_url,
                    json=payload,
                    headers=headers,
                )
                if response.is_success:
                    data = response.json()
                    content = (
                        data.get("choices", [{}])[0]
                        .get("message", {})
                        .get("content", "")
                    )
                    _log_safe("LLM response received tokens=%d", max_tokens)
                    return content

                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < self._max_retries:
                        sleep_time = 2 ** attempt
                        _log_safe(
                            "LLM retry attempt=%d status=%d",
                            attempt + 1,
                            response.status_code,
                        )
                        await asyncio.sleep(sleep_time)
                        continue

                error_text = _redact_key(response.text)
                raise LLMProviderError(
                    f"LLM provider returned {response.status_code}: {error_text}"
                )
            except LLMProviderError:
                raise
            except Exception as exc:
                last_error = exc
                if attempt < self._max_retries:
                    sleep_time = 2 ** attempt
                    _log_safe("LLM network retry attempt=%d", attempt + 1)
                    await asyncio.sleep(sleep_time)
                else:
                    raise LLMProviderError(
                        f"LLM request failed: {exc}"
                    ) from exc

        raise LLMProviderError(
            f"LLM request failed after {self._max_retries + 1} attempts"
        ) from last_error

    async def shutdown(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
