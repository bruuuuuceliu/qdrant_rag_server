"""Table-aware chunking helpers."""

from __future__ import annotations


def chunk_rows(rows: list[list[str]], *, window: int = 50) -> list[str]:
    rendered: list[str] = []
    for start in range(0, len(rows), window):
        batch = rows[start : start + window]
        rendered.append("\n".join(",".join(cell for cell in row) for row in batch))
    return [item for item in rendered if item.strip()]
