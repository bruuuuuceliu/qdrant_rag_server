"""LLM utilities: error classes and key redaction."""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_OPENROUTER_KEY_RE = re.compile(r"sk-or-[A-Za-z0-9._-]+")


class LLMProviderError(Exception):
    """Raised when an LLM provider returns an error or a key is missing."""


def _log_safe(fmt: str, *args: Any) -> None:
    logger.info(_redact_key(fmt % args))


def _redact_key(text: str) -> str:
    return _OPENROUTER_KEY_RE.sub("[REDACTED]", text)
