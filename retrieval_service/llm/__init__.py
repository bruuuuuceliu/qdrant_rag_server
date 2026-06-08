"""LLM providers package.

Provides pluggable chat-completion backends:
- ``OpenRouterLLM`` -- OpenRouter chat-completion API
- ``OpenAICompatibleLLM`` -- OpenAI-compatible API (OpenRouter, OpenAI, Ollama, etc.)

New providers implement the ``LLMProvider`` protocol and register
with ``LLMProviderFactory``.
"""

from __future__ import annotations

from retrieval_service.llm.protocols import ChatMessage, LLMProvider
from retrieval_service.llm.factory import LLMProviderFactory
from retrieval_service.llm.openai_compatible import OpenAICompatibleLLM
from retrieval_service.llm.openrouter import OpenRouterLLM
from retrieval_service.llm.utils import LLMProviderError, _redact_key

OpenRouterClient = OpenRouterLLM
OpenRouterClientError = LLMProviderError

__all__ = [
    "ChatMessage",
    "LLMProvider",
    "LLMProviderError",
    "LLMProviderFactory",
    "OpenAICompatibleLLM",
    "OpenRouterLLM",
    "OpenRouterClient",
    "OpenRouterClientError",
    "_redact_key",
]
