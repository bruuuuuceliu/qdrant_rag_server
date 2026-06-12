"""Raw source storage helpers."""

from __future__ import annotations


def make_raw_storage_key(project_id: str, user_id: str, document_id: str) -> str:
    return f"{project_id}/{user_id}/{document_id}"
