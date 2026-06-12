"""Manager-facing service client protocols."""

from __future__ import annotations

from typing import Any, Protocol


class ProjectDocumentClient(Protocol):
    """Client contract for project-document operations routed by the manager."""

    async def ingest(self, request: Any) -> Any:
        ...

    async def search(self, request: Any) -> Any:
        ...

    async def ingest_status(self, job_id: str) -> Any:
        ...

    async def delete_document(self, request: Any) -> Any:
        ...
