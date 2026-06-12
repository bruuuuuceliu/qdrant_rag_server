"""LLM provider factory.

Maps stable provider names to concrete implementations. Add new
providers (Ollama, Anthropic, Gemini, etc.) by registering them here.
"""

from __future__ import annotations

from retrieval_service.llm.protocols import LLMProvider

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"


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
        from retrieval_service.llm.openai_compatible import OpenAICompatibleLLM
        from retrieval_service.llm.openrouter import OpenRouterLLM

        normalized = provider.strip().lower()
        if normalized == "openrouter":
            return OpenRouterLLM(
                base_url=base_url,
                api_key=api_key,
                default_model=default_model,
                default_max_tokens=default_max_tokens,
                default_temperature=default_temperature,
            )
        if normalized in {"openai_compatible", "openai-compatible", "openai"}:
            return OpenAICompatibleLLM(
                base_url=base_url,
                api_key=api_key,
                default_model=default_model,
                default_max_tokens=default_max_tokens,
                default_temperature=default_temperature,
            )
        raise ValueError(
            "RAG_GENERATION_PROVIDER must be one of: "
            "openrouter, openai_compatible, openai"
        )
