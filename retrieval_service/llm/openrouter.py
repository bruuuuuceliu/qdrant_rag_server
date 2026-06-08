"""OpenRouter LLM provider."""

from __future__ import annotations

from typing import Any

from retrieval_service.llm.openai_compatible import OpenAICompatibleLLM
from retrieval_service.llm.protocols import ChatMessage
from retrieval_service.llm.utils import LLMProviderError

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterLLM(OpenAICompatibleLLM):
    """OpenRouter chat-completion client."""

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
        super().__init__(
            base_url=base_url,
            api_key=api_key,
            default_model=default_model,
            default_max_tokens=default_max_tokens,
            default_temperature=default_temperature,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )

    @property
    def provider_name(self) -> str:
        return "openrouter"

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
        if not selected_key or not selected_key.strip():
            raise LLMProviderError("API key is required for chat completion")
        if not selected_key.startswith("sk-or-"):
            raise LLMProviderError("OpenRouter API key must start with sk-or-")
        return await super().generate_response(
            messages=messages,
            api_key=selected_key,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            response_format=response_format,
        )
