"""OpenRouter generation client with request-scoped API keys.

Legacy re-export shim — all implementations have moved to
``retrieval_service.llm``.  Prefer importing from the new package:

    from retrieval_service.llm import LLMProviderFactory
    from retrieval_service.llm import OpenRouterLLM
    from retrieval_service.llm import OpenAICompatibleLLM

This module remains for backward compatibility.
"""

from __future__ import annotations

from retrieval_service.llm import ChatMessage
from retrieval_service.llm import LLMProvider
from retrieval_service.llm import LLMProviderError as OpenRouterClientError
from retrieval_service.llm import LLMProviderFactory
from retrieval_service.llm import OpenRouterLLM
from retrieval_service.llm import _redact_key

OpenRouterClient = OpenRouterLLM

__all__ = [
    "ChatMessage",
    "LLMProvider",
    "LLMProviderFactory",
    "OpenRouterLLM",
    "OpenRouterClient",
    "OpenRouterClientError",
    "_redact_key",
]
