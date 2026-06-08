"""OpenRouter generation client with request-scoped API keys.

OpenRouter API keys are request-scoped — never stored in logs, cache
entries, database records, or Qdrant payloads.  The client strips the
key from all log output and redacts it in error messages.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

_OPENROUTER_KEY_RE = re.compile(r"sk-or-[a-zA-Z0-9]+")


class OpenRouterClientError(Exception):
    """Raised when OpenRouter returns an error or the key is missing."""


class OpenRouterClient:
    """Asynchronous OpenRouter client."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
    ) -> None:
        self._timeout = timeout_seconds
        self._max_retries = max_retries

    async def generate(
        self,
        *,
        prompt: str,
        api_key: str,
        model: str = "openai/gpt-4o-mini",
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> str:
        if not api_key or not api_key.startswith("sk-or-"):
            raise OpenRouterClientError(
                "valid OpenRouter API key is required (must start with sk-or-)"
            )

        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

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
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.post(
                        OPENROUTER_API_URL,
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


def _log_safe(fmt: str, *args: Any) -> None:
    logger.info(_redact_key(fmt % args))


def _redact_key(text: str) -> str:
    return _OPENROUTER_KEY_RE.sub("[REDACTED]", text)
