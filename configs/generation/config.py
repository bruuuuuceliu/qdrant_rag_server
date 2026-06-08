"""Generation configuration helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from configs.config import get_bool_value, get_int_value, get_value


CONFIG_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True, slots=True)
class GenerationSettings:
    enabled: bool
    provider: str
    model: str
    api_key: str
    base_url: str
    max_tokens: int
    temperature: float


def load_generation_settings(values: dict[str, str]) -> GenerationSettings:
    temperature_value = get_value(values, "RAG_GENERATION_TEMPERATURE", "0.7")
    try:
        temperature = float(temperature_value)
    except ValueError as exc:
        raise ValueError("RAG_GENERATION_TEMPERATURE must be a number") from exc

    return GenerationSettings(
        enabled=get_bool_value(values, "RAG_GENERATION_ENABLED", False),
        provider=get_value(values, "RAG_GENERATION_PROVIDER", "openrouter"),
        model=get_value(values, "RAG_GENERATION_MODEL", "openai/gpt-4o-mini"),
        api_key=get_value(values, "RAG_GENERATION_API_KEY", ""),
        base_url=get_value(
            values,
            "RAG_GENERATION_BASE_URL",
            "https://openrouter.ai/api/v1/chat/completions",
        ),
        max_tokens=get_int_value(values, "RAG_GENERATION_MAX_TOKENS", 1024),
        temperature=temperature,
    )
