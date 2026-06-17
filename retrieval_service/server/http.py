"""Minimal HTTP transport for the retrieval API server context."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
from typing import Any

from configs.retrieval.config import RetrievalHttpSettings
from retrieval_service.retrieval import RetrievalResponseEnvelope


@dataclass(frozen=True, slots=True)
class RetrievalHttpRequest:
    method: str
    path: str
    body: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RetrievalHttpResponse:
    status: int
    body: bytes
    headers: dict[str, str]

    @classmethod
    def json(cls, *, status: int, payload: dict[str, Any]) -> "RetrievalHttpResponse":
        return cls(
            status=status,
            body=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={"content-type": "application/json"},
        )


class RetrievalHttpApp:
    """Dispatches HTTP-shaped requests to a retrieval API context."""

    def __init__(self, *, api: Any) -> None:
        self._api = api

    async def handle(self, request: RetrievalHttpRequest) -> RetrievalHttpResponse:
        method = request.method.upper()
        path = request.path.split("?", 1)[0]
        if method == "GET" and path == "/health":
            return RetrievalHttpResponse.json(status=200, payload={"ok": True})
        if method != "POST":
            return _failure_response(
                request_id="http",
                code="not_found",
                message=f"unsupported route: {method} {path}",
                status=404,
            )

        payload, error = _json_payload(request.body)
        if error is not None:
            return error

        request_id = str(payload.get("request_id") or "http")
        try:
            if path == "/search":
                response = await self._api.search(
                    payload,
                    fallback_request_id=request_id,
                )
            elif path == "/documents/delete":
                response = await self._api.delete_document(
                    payload,
                    fallback_request_id=request_id,
                )
            elif path == "/documents/raw":
                response = await self._api.get_raw_document(
                    payload,
                    fallback_request_id=request_id,
                )
            else:
                return _failure_response(
                    request_id=request_id,
                    code="not_found",
                    message=f"unsupported route: {method} {path}",
                    status=404,
                )
        except Exception as exc:
            return _failure_response(
                request_id=request_id,
                code="internal_error",
                message=str(exc) or "retrieval HTTP request failed",
                status=500,
            )
        return RetrievalHttpResponse.json(
            status=_status_for_envelope(response),
            payload=response,
        )


def create_http_app(*, api: Any) -> RetrievalHttpApp:
    return RetrievalHttpApp(api=api)


async def serve_http(
    *,
    app: RetrievalHttpApp,
    settings: RetrievalHttpSettings,
) -> asyncio.AbstractServer:
    server = await asyncio.start_server(
        lambda reader, writer: _handle_connection(
            app=app,
            reader=reader,
            writer=writer,
            read_timeout=settings.read_timeout,
        ),
        settings.host,
        settings.port,
    )
    return server


async def _handle_connection(
    *,
    app: RetrievalHttpApp,
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    read_timeout: float,
) -> None:
    try:
        request = await asyncio.wait_for(_read_request(reader), timeout=read_timeout)
        response = await app.handle(request)
        writer.write(_http_response(response))
        await writer.drain()
    except Exception:
        response = _failure_response(
            request_id="http",
            code="internal_error",
            message="retrieval HTTP request failed",
            status=500,
        )
        writer.write(_http_response(response))
        await writer.drain()
    finally:
        writer.close()
        await writer.wait_closed()


async def _read_request(reader: asyncio.StreamReader) -> RetrievalHttpRequest:
    header_bytes = await reader.readuntil(b"\r\n\r\n")
    header_text = header_bytes.decode("iso-8859-1")
    lines = header_text.split("\r\n")
    request_line = lines[0].split()
    if len(request_line) < 2:
        return RetrievalHttpRequest(method="", path="")
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        headers[key.strip().lower()] = value.strip()
    content_length = int(headers.get("content-length", "0") or "0")
    body = await reader.readexactly(content_length) if content_length else b""
    return RetrievalHttpRequest(
        method=request_line[0],
        path=request_line[1],
        body=body,
        headers=headers,
    )


def _http_response(response: RetrievalHttpResponse) -> bytes:
    reason = _reason_phrase(response.status)
    headers = {
        "content-length": str(len(response.body)),
        "connection": "close",
        **response.headers,
    }
    header_lines = [f"HTTP/1.1 {response.status} {reason}"]
    header_lines.extend(f"{key}: {value}" for key, value in headers.items())
    return ("\r\n".join(header_lines) + "\r\n\r\n").encode("ascii") + response.body


def _json_payload(
    body: bytes,
) -> tuple[dict[str, Any], RetrievalHttpResponse | None]:
    if not body:
        return {}, None
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}, _failure_response(
            request_id="http",
            code="validation_error",
            message="request body must be valid JSON",
            status=400,
        )
    if not isinstance(payload, dict):
        return {}, _failure_response(
            request_id="http",
            code="validation_error",
            message="request body must be a JSON object",
            status=400,
        )
    return dict(payload), None


def _failure_response(
    *,
    request_id: str,
    code: str,
    message: str,
    status: int,
) -> RetrievalHttpResponse:
    return RetrievalHttpResponse.json(
        status=status,
        payload=RetrievalResponseEnvelope.failure(
            request_id=request_id,
            code=code,
            message=message,
            retryable=False,
        ).to_mapping(),
    )


def _status_for_envelope(envelope: dict[str, Any]) -> int:
    if envelope.get("ok") is True:
        return 200
    error = envelope.get("error")
    code = error.get("code") if isinstance(error, dict) else ""
    if code == "validation_error":
        return 400
    return 500


def _reason_phrase(status: int) -> str:
    return {
        200: "OK",
        400: "Bad Request",
        404: "Not Found",
        500: "Internal Server Error",
    }.get(status, "OK")
