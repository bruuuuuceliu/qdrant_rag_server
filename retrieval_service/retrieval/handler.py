"""Transport-neutral retrieval API handler."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from retrieval_service.retrieval.contracts import (
    MemorySearchCommand,
    RetrievalDeleteDocumentCommand,
    RetrievalRawDocumentCommand,
    RetrievalResponseEnvelope,
    RetrievalSearchCommand,
    memory_search_result_to_mapping,
    raw_document_result_to_mapping,
    search_result_to_mapping,
)


@dataclass(slots=True)
class RetrievalApiHandler:
    """Dispatches retrieval API payloads through a retrieval app context."""

    app: Any

    async def handle_search(
        self,
        payload: dict[str, Any],
        *,
        fallback_request_id: str,
    ) -> dict[str, Any]:
        return await self._handle(
            payload,
            fallback_request_id=fallback_request_id,
            command_factory=RetrievalSearchCommand.from_payload,
            operation=lambda command: self.app.search(command.to_service_request()),
            result_mapper=search_result_to_mapping,
        )

    async def handle_memory_search(
        self,
        payload: dict[str, Any],
        *,
        fallback_request_id: str,
    ) -> dict[str, Any]:
        command = MemorySearchCommand.from_payload(
            payload, fallback_request_id=fallback_request_id
        )
        try:
            result = await self.app.search_memory(
                command.to_service_request(),
                owner_id=command.owner_id or command.user_id,
                agent_id=command.agent_id,
            )
        except ValueError as exc:
            return RetrievalResponseEnvelope.failure(
                request_id=command.request_id,
                code="validation_error",
                message=str(exc),
                retryable=False,
            ).to_mapping()
        except Exception as exc:
            return RetrievalResponseEnvelope.failure(
                request_id=command.request_id,
                code="internal_error",
                message=str(exc),
                retryable=True,
            ).to_mapping()
        return RetrievalResponseEnvelope.success(
            request_id=command.request_id,
            result=memory_search_result_to_mapping(
                result, agent_id=command.agent_id, owner_id=command.owner_id
            ),
        ).to_mapping()

    async def handle_delete_document(
        self,
        payload: dict[str, Any],
        *,
        fallback_request_id: str,
    ) -> dict[str, Any]:
        return await self._handle(
            payload,
            fallback_request_id=fallback_request_id,
            command_factory=RetrievalDeleteDocumentCommand.from_payload,
            operation=lambda command: self.app.delete_document(
                command.to_service_request()
            ),
            result_mapper=lambda _result: {"deleted": True},
        )

    async def handle_raw_document(
        self,
        payload: dict[str, Any],
        *,
        fallback_request_id: str,
    ) -> dict[str, Any]:
        return await self._handle(
            payload,
            fallback_request_id=fallback_request_id,
            command_factory=RetrievalRawDocumentCommand.from_payload,
            operation=lambda command: self.app.get_raw_document(
                command.to_service_request()
            ),
            result_mapper=raw_document_result_to_mapping,
        )

    async def _handle(
        self,
        payload: dict[str, Any],
        *,
        fallback_request_id: str,
        command_factory: Callable[..., Any],
        operation: Callable[[Any], Awaitable[Any]],
        result_mapper: Callable[[Any], dict[str, Any]],
    ) -> dict[str, Any]:
        request_id = _request_id(payload, fallback_request_id=fallback_request_id)
        try:
            command = command_factory(payload, fallback_request_id=fallback_request_id)
            request_id = command.request_id
            result = await operation(command)
        except ValueError as exc:
            return RetrievalResponseEnvelope.failure(
                request_id=request_id,
                code="validation_error",
                message=str(exc),
                retryable=False,
            ).to_mapping()
        except Exception as exc:
            return RetrievalResponseEnvelope.failure(
                request_id=request_id,
                code="internal_error",
                message=str(exc),
                retryable=True,
            ).to_mapping()

        return RetrievalResponseEnvelope.success(
            request_id=request_id,
            result=result_mapper(result),
        ).to_mapping()


def _request_id(payload: dict[str, Any], *, fallback_request_id: str) -> str:
    return str(payload.get("request_id") or fallback_request_id)
