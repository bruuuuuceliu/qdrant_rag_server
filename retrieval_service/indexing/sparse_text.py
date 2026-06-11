"""Sparse-text preparation and payload attachment."""

from __future__ import annotations

from typing import Any


def _build_sparse_text(
    text: str,
    metadata: dict[str, Any],
    *,
    lemmatize: bool,
) -> str:
    del metadata
    normalized = " ".join(text.split())
    if lemmatize:
        return normalized.casefold()
    return normalized


def _attach_sparse_text(
    payloads: list[Any],
    sparse_texts: list[str],
    *,
    field_name: str,
) -> list[Any]:
    return [
        _SparsePayload(payload=payload, field_name=field_name, sparse_text=sparse_text)
        for payload, sparse_text in zip(payloads, sparse_texts)
    ]


class _SparsePayload:
    def __init__(self, *, payload: Any, field_name: str, sparse_text: str) -> None:
        self._payload = payload
        self._field_name = field_name
        self._sparse_text = sparse_text

    def to_qdrant_payload(self) -> dict[str, Any]:
        rendered = dict(self._payload.to_qdrant_payload())
        rendered[self._field_name] = self._sparse_text
        return rendered

    def point_identity(self) -> tuple[str, ...]:
        return self._payload.point_identity()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._payload, name)
