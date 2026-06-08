"""OpenRouter generation client with request-scoped API keys.

OpenRouter API keys are request-scoped — never stored in logs, cache
entries, database records, or Qdrant payloads.  The client strips the
key from all log output and redacts it in error messages.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Protocol

import httpx

logger = logging.getLogger(__name__)

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

_OPENROUTER_KEY_RE = re.compile(r"sk-or-[a-zA-Z0-9]+")

ChatMessage = dict[str, str]


class LLMProvider(Protocol):
    """Protocol for async chat-completion providers."""

    async def initialize(self) -> "LLMProvider":
        """Open provider resources and return self."""

    async def generate_response(
        self,
        *,
        messages: list[ChatMessage],
        api_key: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> str: ...

    async def shutdown(self) -> None:
        """Close provider resources."""


class LLMProviderFactory:
    """Creates configured LLM providers by stable provider name."""

    @staticmethod
    def create(
        provider: str,
        *,
        base_url: str = OPENROUTER_API_URL,
        api_key: str = "",
        default_model: str = "openai/gpt-4o-mini",
        default_max_tokens: int = 1024,
        default_temperature: float = 0.7,
    ) -> LLMProvider:
        normalized = provider.strip().lower()
        if normalized in {"openrouter", "openai_compatible", "openai-compatible"}:
            return OpenRouterClient(
                base_url=base_url,
                api_key=api_key,
                default_model=default_model,
                default_max_tokens=default_max_tokens,
                default_temperature=default_temperature,
            )
        raise ValueError(
            "RAG_GENERATION_PROVIDER must be one of: "
            "openrouter, openai_compatible"
        )


class OpenRouterClientError(Exception):
    """Raised when OpenRouter returns an error or the key is missing."""


class OpenRouterClient:
    """Asynchronous OpenRouter client."""

    def __init__(
        self,
        *,
        base_url: str = OPENROUTER_API_URL,
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
        return "openrouter"

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
        if not api_key or not api_key.startswith("sk-or-"):
            raise OpenRouterClientError(
                "valid OpenRouter API key is required (must start with sk-or-)"
            )
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
            "HTTP-Referer": "http://localhost",
            "X-Title": "qdrant-rag-server",
        }

        _log_safe("OpenRouter request model=%s tokens=%d", model, max_tokens)

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
                    _log_safe("OpenRouter response received tokens=%d", max_tokens)
                    return content

                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < self._max_retries:
                        sleep_time = 2 ** attempt
                        _log_safe(
                            "OpenRouter retry attempt=%d status=%d",
                            attempt + 1,
                            response.status_code,
                        )
                        import asyncio
                        await asyncio.sleep(sleep_time)
                        continue

                error_text = _redact_key(response.text)
                raise OpenRouterClientError(
                    f"OpenRouter returned {response.status_code}: {error_text}"
                )
            except OpenRouterClientError:
                raise
            except Exception as exc:
                last_error = exc
                if attempt < self._max_retries:
                    sleep_time = 2 ** attempt
                    _log_safe("OpenRouter network retry attempt=%d", attempt + 1)
                    import asyncio
                    await asyncio.sleep(sleep_time)
                else:
                    raise OpenRouterClientError(
                        f"OpenRouter request failed: {exc}"
                    ) from exc

        raise OpenRouterClientError(
            f"OpenRouter request failed after {self._max_retries + 1} attempts"
        ) from last_error

    async def shutdown(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


def _log_safe(fmt: str, *args: Any) -> None:
    logger.info(_redact_key(fmt % args))


def _redact_key(text: str) -> str:
    return _OPENROUTER_KEY_RE.sub("[REDACTED]", text)
