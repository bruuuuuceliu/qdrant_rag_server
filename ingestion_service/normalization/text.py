"""Text normalization helpers."""

from __future__ import annotations

import re


def normalize_text(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def split_paragraphs(value: str) -> list[str]:
    return [part.strip() for part in normalize_text(value).split("\n\n") if part.strip()]
