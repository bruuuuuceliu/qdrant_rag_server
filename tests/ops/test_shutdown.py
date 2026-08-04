"""Graceful shutdown helper tests."""

from __future__ import annotations

import asyncio
import os
import signal

import pytest

from shared.ops.shutdown import run_service, signal_stop_event


async def test_signal_stop_event_fires_on_signal() -> None:
    async with signal_stop_event(signals=(signal.SIGUSR1,)) as stop:
        os.kill(os.getpid(), signal.SIGUSR1)
        await asyncio.wait_for(stop.wait(), timeout=2)
        assert stop.is_set()


async def test_run_service_invokes_shutdown_when_serve_raises() -> None:
    stopped: list[str] = []

    async def serve() -> None:
        raise RuntimeError("boom")

    async def shutdown() -> None:
        stopped.append("shutdown")

    with pytest.raises(RuntimeError, match="boom"):
        await run_service(serve=serve, shutdown=shutdown, grace_timeout=5)
    assert stopped == ["shutdown"]


async def test_run_service_invokes_shutdown_when_serve_completes() -> None:
    served: list[str] = []
    stopped: list[str] = []

    async def serve() -> None:
        served.append("serve")
        return None

    async def shutdown() -> None:
        stopped.append("shutdown")

    await run_service(serve=serve, shutdown=shutdown, grace_timeout=5)
    assert served == ["serve"]
    assert stopped == ["shutdown"]


async def test_run_service_waits_until_signal_then_shuts_down() -> None:
    stopped: list[str] = []

    async def serve() -> None:
        # A blocking loop that a signal-driven stop cancels.
        while True:
            await asyncio.sleep(3600)

    async def shutdown() -> None:
        stopped.append("shutdown")

    # Signal the process after a short delay; the handler installed by
    # run_service cancels the serve loop and calls shutdown.
    async def fire() -> None:
        await asyncio.sleep(0.05)
        os.kill(os.getpid(), signal.SIGUSR1)

    task = asyncio.create_task(
        run_service(serve=serve, shutdown=shutdown, grace_timeout=5, signals=(signal.SIGUSR1,))
    )
    fire_task = asyncio.create_task(fire())
    await asyncio.wait_for(task, timeout=5)
    await fire_task
    assert stopped == ["shutdown"]
