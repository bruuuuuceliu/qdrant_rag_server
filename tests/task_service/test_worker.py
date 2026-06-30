"""Task service worker tests."""

from __future__ import annotations

import asyncio

import pytest

import task_service.worker as worker


class Context:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    async def start_runtime(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True


@pytest.mark.asyncio
async def test_task_service_worker_uses_runtime_composition(monkeypatch: pytest.MonkeyPatch) -> None:
    context = Context()

    def fake_create_task_service_context():
        return context

    async def fake_sleep(_seconds: int) -> None:
        raise asyncio.CancelledError()

    monkeypatch.setattr(worker, "create_task_service_context", fake_create_task_service_context)
    monkeypatch.setattr(worker.asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await worker.serve_forever()

    assert context.started is True
    assert context.stopped is True
