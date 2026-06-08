"""LLM provider protocol and shared types."""

from __future__ import annotations

from typing import Any, Protocol

ChatMessage = dict[str, str]


class LLMProvider(Protocol):
    """Protocol for async chat-completion providers."""

    async def initialize(self) -> "LLMProvider":
        """Open provider resources and return self."""
        ...

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
        """Return generated text for chat messages."""
        ...

    async def shutdown(self) -> None:
        """Close provider resources."""
        ...
