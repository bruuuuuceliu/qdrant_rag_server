"""Retrieval service app context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class RetrievalAppContext:
    retrieval_service: Any

    async def search(self, request: Any) -> Any:
        return await self.retrieval_service.search(request)

    async def search_memory(self, request: Any, *, owner_id: str = "", agent_id: str = "") -> Any:
        return await self.retrieval_service.search_memory(
            request, owner_id=owner_id, agent_id=agent_id
        )

    async def delete_document(self, request: Any) -> Any:
        return await self.retrieval_service.delete_document(request)

    async def get_raw_document(self, request: Any) -> Any:
        return await self.retrieval_service.get_raw_document(request)

    async def shutdown(self) -> None:
        shutdown = getattr(self.retrieval_service, "shutdown", None)
        if shutdown is not None:
            await shutdown()


async def create_app(*, retrieval_service: Any) -> RetrievalAppContext:
    return RetrievalAppContext(retrieval_service=retrieval_service)
