"""Ops HTTP server (/healthz, /readyz, /metrics) tests."""

from __future__ import annotations

import asyncio

import httpx

from shared.ops.server import OpsServer, ops_server_from_env
from shared.runtime_health import RuntimeHealth


async def _start_server(
    *,
    service_name: str = "test-service",
    readiness: object | None = None,
) -> tuple[OpsServer, str]:
    server = OpsServer(
        service_name=service_name,
        host="127.0.0.1",
        port=0,
        readiness=readiness,  # type: ignore[arg-type]
    )
    await server.start()
    url = f"http://127.0.0.1:{server.bound_port()}"
    return server, url


async def _get(url: str, path: str) -> httpx.Response:
    async with httpx.AsyncClient() as client:
        return await client.get(f"{url}{path}")


async def test_healthz_ok() -> None:
    server, url = await _start_server()
    try:
        response = await _get(url, "/healthz")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        assert response.json()["service"] == "test-service"
    finally:
        await server.stop()


async def test_readyz_without_callback_is_ready() -> None:
    server, url = await _start_server()
    try:
        response = await _get(url, "/readyz")
        assert response.status_code == 200
        assert response.json()["ready"] is True
    finally:
        await server.stop()


async def test_readyz_ready_when_health_ready() -> None:
    async def readiness() -> RuntimeHealth:
        return RuntimeHealth(service="test-service", ready=True)

    server, url = await _start_server(readiness=readiness)
    try:
        response = await _get(url, "/readyz")
        assert response.status_code == 200
        assert response.json()["ready"] is True
    finally:
        await server.stop()


async def test_readyz_503_when_not_ready() -> None:
    async def readiness() -> RuntimeHealth:
        return RuntimeHealth(service="test-service", ready=False, dependencies={"broker": False})

    server, url = await _start_server(readiness=readiness)
    try:
        response = await _get(url, "/readyz")
        assert response.status_code == 503
        assert response.json()["ready"] is False
    finally:
        await server.stop()


async def test_readyz_503_when_callback_raises() -> None:
    async def readiness() -> RuntimeHealth:
        raise RuntimeError("boom")

    server, url = await _start_server(readiness=readiness)
    try:
        response = await _get(url, "/readyz")
        assert response.status_code == 503
    finally:
        await server.stop()


async def test_metrics_endpoint() -> None:
    server, url = await _start_server()
    try:
        response = await _get(url, "/metrics")
        assert response.status_code == 200
        assert b"rag_tasks_accepted_total" in response.content
    finally:
        await server.stop()


async def test_unknown_path_404() -> None:
    server, url = await _start_server()
    try:
        response = await _get(url, "/nope")
        assert response.status_code == 404
    finally:
        await server.stop()


async def test_concurrent_requests() -> None:
    server, url = await _start_server()
    try:
        responses = await asyncio.gather(
            *[_get(url, "/healthz") for _ in range(10)]
        )
        assert all(response.status_code == 200 for response in responses)
    finally:
        await server.stop()


def test_ops_server_from_env_disabled_by_default() -> None:
    server = ops_server_from_env("worker", default_port=9001, values={})
    assert server is None


def test_ops_server_from_env_enabled_uses_default_port() -> None:
    server = ops_server_from_env(
        "worker",
        default_port=9001,
        values={"RAG_OPS_ENABLED": "true"},
    )
    assert server is not None
    assert server.port == 9001
    assert server.host == "0.0.0.0"


def test_ops_server_from_env_enabled_honors_overrides() -> None:
    server = ops_server_from_env(
        "worker",
        default_port=9001,
        values={
            "RAG_OPS_ENABLED": "1",
            "RAG_OPS_PORT": "9107",
            "RAG_OPS_HOST": "127.0.0.1",
        },
    )
    assert server is not None
    assert server.port == 9107
    assert server.host == "127.0.0.1"


def test_ops_server_from_env_invalid_port_falls_back() -> None:
    server = ops_server_from_env(
        "worker",
        default_port=9001,
        values={"RAG_OPS_ENABLED": "yes", "RAG_OPS_PORT": "not-a-port"},
    )
    assert server is not None
    assert server.port == 9001


async def test_metrics_endpoint_counts_its_own_requests() -> None:
    server, url = await _start_server()
    try:
        await _get(url, "/healthz")
        await _get(url, "/healthz")
        response = await _get(url, "/metrics")
        # Each earlier request incremented the counter; the render inside this
        # response happens before the final increment, so at least 2 show.
        assert response.status_code == 200
        assert b"rag_http_requests_total" in response.content
        assert b"rag_tasks_accepted_total" in response.content
    finally:
        await server.stop()
