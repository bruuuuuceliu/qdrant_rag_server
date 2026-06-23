"""Ingestion API server context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ingestion_service.server.handler import IngestionApiHandler


@dataclass(slots=True)
class IngestionApiServerContext:
    ingestion_app: Any
    handler: IngestionApiHandler

    async def get_status(
        self,
        payload: dict[str, Any],
        *,
        fallback_request_id: str = "ingestion-status",
    ) -> dict[str, Any]:
        return await self.handler.get_status(
            payload,
            fallback_request_id=fallback_request_id,
        )

    async def health(
        self,
        payload: dict[str, Any] | None = None,
        *,
        fallback_request_id: str = "ingestion-health",
    ) -> dict[str, Any]:
        return await self.handler.health(
            payload,
            fallback_request_id=fallback_request_id,
        )

    async def shutdown(self) -> None:
        shutdown = getattr(self.ingestion_app, "shutdown", None)
        if shutdown is not None:
            await shutdown()


async def create_api_app(*, ingestion_app: Any) -> IngestionApiServerContext:
    return IngestionApiServerContext(
        ingestion_app=ingestion_app,
        handler=IngestionApiHandler(app=ingestion_app),
    )
