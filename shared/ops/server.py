"""Minimal asyncio HTTP ops surface for service processes.

Every worker exposes three GET endpoints on a small dependency-free HTTP/1.1
server (hand-rolled on ``asyncio.start_server``; connection close is used to
avoid keep-alive state):

- ``/healthz``  200 when the process is alive (liveness probe).
- ``/readyz``   200 when the service reports ready, 503 otherwise (readiness).
- ``/metrics``  Prometheus text exposition (from ``shared.ops.metrics``).

The server is intentionally narrow: no routing framework, no TLS here (the
deployment network is private; TLS terminates at the platform edge). Readiness
comes from a per-worker callback returning a ``shared.runtime_health.RuntimeHealth``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from shared.ops import metrics
from shared.runtime_health import RuntimeHealth

logger = logging.getLogger(__name__)

_STATUS_LINES = {
    200: "OK",
    400: "Bad Request",
    404: "Not Found",
    405: "Method Not Allowed",
    500: "Internal Server Error",
    503: "Service Unavailable",
}

_READ_LINE_TIMEOUT = 5.0


@dataclass(slots=True)
class OpsServer:
    """HTTP health/readiness/metrics server for one service process."""

    service_name: str
    host: str = "0.0.0.0"
    port: int = 0
    readiness: Callable[[], Awaitable[RuntimeHealth]] | None = None
    _server: asyncio.Server | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle_connection,
            host=self.host,
            port=self.port,
            limit=64 * 1024,
        )
        bound = self.bound_port()
        logger.info(
            "ops server listening service=%s host=%s port=%s",
            self.service_name,
            self.host,
            bound,
        )

    async def stop(self) -> None:
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()
        self._server = None

    def bound_port(self) -> int:
        if self._server is None or not self._server.sockets:
            return self.port
        return int(self._server.sockets[0].getsockname()[1])

    # -- Connection handling --------------------------------------------------

    async def _handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        metrics.http_requests_in_flight.inc()
        status = 500
        path = ""
        try:
            request_line = await asyncio.wait_for(reader.readline(), timeout=_READ_LINE_TIMEOUT)
            if not request_line:
                return
            parts = request_line.decode("latin-1").strip().split()
            if len(parts) < 2:
                await self._write(writer, 400, b'{"error":"malformed request line"}')
                return
            method, path = parts[0], parts[1]
            if method != "GET":
                await self._write(writer, 405, b'{"error":"method not allowed"}')
                status = 405
                return
            await self._drain_headers(reader)
            if path in ("/healthz", "/health"):
                status = 200
                await self._write(writer, 200, _json_bytes({"status": "ok", "service": self.service_name}))
            elif path == "/readyz":
                await self._handle_readyz(writer)
                status = 200
            elif path == "/metrics":
                status = 200
                await self._write(
                    writer,
                    200,
                    metrics.render(),
                    metrics.CONTENT_TYPE_LATEST,
                )
            else:
                status = 404
                await self._write(writer, 404, _json_bytes({"error": "not found"}))
        except TimeoutError:
            logger.debug("ops request timed out path=%s", path)
        except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError):
            pass
        except Exception:
            logger.exception("ops request failed path=%s", path)
            with contextlib.suppress(Exception):
                await self._write(writer, 500, _json_bytes({"error": "internal error"}))
        finally:
            metrics.http_requests_in_flight.dec()
            metrics.http_requests.labels(method="GET", path=path or "", status=status).inc()
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    async def _handle_readyz(self, writer: asyncio.StreamWriter) -> None:
        if self.readiness is None:
            await self._write(writer, 200, _json_bytes({"status": "ok", "service": self.service_name, "ready": True}))
            return
        try:
            health = await asyncio.wait_for(self.readiness(), timeout=_READ_LINE_TIMEOUT)
        except TimeoutError:
            logger.warning("readiness callback timed out service=%s", self.service_name)
            await self._write(writer, 503, _json_bytes({"status": "unavailable", "service": self.service_name, "ready": False}))
            return
        except Exception:
            logger.exception("readiness callback failed service=%s", self.service_name)
            await self._write(writer, 503, _json_bytes({"status": "unavailable", "service": self.service_name, "ready": False}))
            return
        ready = bool(getattr(health, "ready", False))
        metrics.service_ready.labels(service=self.service_name).set(1 if ready else 0)
        if ready:
            await self._write(writer, 200, _json_bytes(health.to_payload()))
        else:
            await self._write(writer, 503, _json_bytes(health.to_payload()))

    @staticmethod
    async def _drain_headers(reader: asyncio.StreamReader) -> None:
        while True:
            line = await asyncio.wait_for(reader.readline(), timeout=_READ_LINE_TIMEOUT)
            if line in (b"\r\n", b"\n", b""):
                return

    @staticmethod
    async def _write(
        writer: asyncio.StreamWriter,
        status: int,
        body: bytes,
        content_type: str = "application/json",
    ) -> None:
        reason = _STATUS_LINES.get(status, "OK")
        head = (
            f"HTTP/1.1 {status} {reason}\r\n"
            f"Content-Type: {content_type}\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).encode("ascii")
        writer.write(head + body)
        await writer.drain()


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, default=str, separators=(",", ":")).encode("utf-8")


def ops_server_from_env(
    service_name: str,
    *,
    default_port: int,
    readiness: Callable[[], Awaitable[RuntimeHealth]] | None = None,
    values: dict[str, str] | None = None,
) -> OpsServer | None:
    """Build an ``OpsServer`` from ``RAG_OPS_*`` environment variables.

    Returns ``None`` (no ops surface) unless ``RAG_OPS_ENABLED`` is truthy, so
    the local runner and unit tests are unaffected. Production deployments set
    ``RAG_OPS_ENABLED=true`` and pin ``RAG_OPS_PORT`` per service.

    - ``RAG_OPS_ENABLED``   "1"/"true"/"yes"/"on" enables the surface.
    - ``RAG_OPS_HOST``      default ``0.0.0.0``.
    - ``RAG_OPS_PORT``      default ``default_port`` (each service supplies its
      own so many workers can coexist on one host).
    """
    values = os.environ if values is None else values
    enabled = values.get("RAG_OPS_ENABLED", "").strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        return None
    host = values.get("RAG_OPS_HOST", "0.0.0.0").strip() or "0.0.0.0"
    try:
        port = int(values.get("RAG_OPS_PORT", str(default_port)))
    except ValueError:
        port = default_port
    return OpsServer(
        service_name=service_name,
        host=host,
        port=port,
        readiness=readiness,
    )
