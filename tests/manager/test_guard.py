"""Manager public-edge guard (rate limiting + payload cap) tests."""

from __future__ import annotations

from types import SimpleNamespace

import grpc
import pytest

from configs.manager import load_manager_guard_settings
from manager_service.server.grpc.server import ManagerGuard, ManagerRagServiceServicer
from shared.transport.grpc.generated import retrieval_service_pb2


class _FakeManager:
    def __init__(self) -> None:
        self.calls = 0

    async def search(self, request, *, context=None):
        self.calls += 1
        return SimpleNamespace(chunks=[], elapsed_ms=1, cache_hit=False)


class _FakeContext:
    def __init__(self) -> None:
        self.aborted: tuple[grpc.StatusCode, str] | None = None

    async def abort(self, code: grpc.StatusCode, details: str) -> None:
        self.aborted = (code, details)
        raise _RequestRejected()


class _RequestRejected(RuntimeError):
    pass


def _servicer(*, burst: int, manager: _FakeManager | None = None) -> tuple[ManagerRagServiceServicer, _FakeManager]:
    fake = manager or _FakeManager()
    servicer = ManagerRagServiceServicer(
        manager=fake,
        guard=ManagerGuard(rate_per_second=0.0, burst=burst, max_request_bytes=1024),
    )
    return servicer, fake


async def test_guard_allows_requests_within_burst() -> None:
    servicer, fake = _servicer(burst=2)
    for _ in range(2):
        response = await servicer.Search(retrieval_service_pb2.SearchRequest(), _FakeContext())
        assert response.chunks == []
    assert fake.calls == 2


async def test_guard_rejects_when_burst_exhausted() -> None:
    servicer, _ = _servicer(burst=1)
    await servicer.Search(retrieval_service_pb2.SearchRequest(), _FakeContext())
    context = _FakeContext()
    with pytest.raises(_RequestRejected):
        await servicer.Search(retrieval_service_pb2.SearchRequest(), context)
    assert context.aborted == (grpc.StatusCode.RESOURCE_EXHAUSTED, "manager rate limit exceeded")


async def test_no_guard_means_no_rate_limit() -> None:
    fake = _FakeManager()
    servicer = ManagerRagServiceServicer(manager=fake)
    for _ in range(5):
        await servicer.Search(retrieval_service_pb2.SearchRequest(), _FakeContext())
    assert fake.calls == 5


async def test_health_check_is_not_rate_limited() -> None:
    servicer, _ = _servicer(burst=1)
    await servicer.Search(retrieval_service_pb2.SearchRequest(), _FakeContext())
    response = await servicer.HealthCheck(
        retrieval_service_pb2.HealthCheckRequest(),
        _FakeContext(),
    )
    assert response.status == "healthy"


def test_manager_guard_acquire_exhausts() -> None:
    guard = ManagerGuard(rate_per_second=0.0, burst=2)
    assert guard.acquire()
    assert guard.acquire()
    assert not guard.acquire()


def test_load_manager_guard_settings_defaults() -> None:
    settings = load_manager_guard_settings({})
    assert settings.rate_limit_per_second == 100.0
    assert settings.rate_limit_burst == 200
    assert settings.max_request_bytes == 4 * 1024 * 1024


def test_load_manager_guard_settings_from_env() -> None:
    settings = load_manager_guard_settings(
        {
            "MANAGER_RATE_LIMIT_REQUESTS_PER_SECOND": "50",
            "MANAGER_RATE_LIMIT_BURST": "10",
            "MANAGER_MAX_REQUEST_BYTES": "2048",
        }
    )
    assert settings.rate_limit_per_second == 50.0
    assert settings.rate_limit_burst == 10
    assert settings.max_request_bytes == 2048
