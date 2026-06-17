"""HTTP client for the retrieval API transport."""

from __future__ import annotations

from typing import Any

import httpx


class RetrievalApiHttpClient:
    """Async JSON client for retrieval response-envelope endpoints."""

    def __init__(
        self,
        *,
        base_url: str,
        timeout: float = 30.0,
        http_client: Any | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(timeout=timeout)

    async def search(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._post("/search", payload)

    async def delete_document(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._post("/documents/delete", payload)

    async def get_raw_document(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._post("/documents/raw", payload)

    async def shutdown(self) -> None:
        if not self._owns_client:
            return
        close = getattr(self._client, "aclose", None)
        if close is not None:
            await close()

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self._client.post(
            f"{self._base_url}{path}",
            json=payload,
        )
        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError(
                f"retrieval HTTP response from {path} was not valid JSON"
            ) from exc
        if not isinstance(data, dict):
            raise RuntimeError(
                f"retrieval HTTP response from {path} must be a JSON object"
            )
        return dict(data)
