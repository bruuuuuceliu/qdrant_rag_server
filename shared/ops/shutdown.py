"""Signal-driven graceful shutdown helpers for service entrypoints.

The historical worker entrypoints each rolled their own wait loop (``while
True: asyncio.sleep(3600)``, gRPC ``wait_for_termination()``, or a manual
``asyncio.Event``) and most did not handle SIGTERM at all — asyncio.run only
installs a SIGINT handler, so a SIGTERM killed the process without running
cleanup. ``run_service`` standardizes the pattern: register SIGTERM/SIGINT, run
the service until either the signal fires or the main task ends, cancel in
flight work, stop the ops surface, then call the graceful ``shutdown()`` hook
with a bounded grace period.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)


@contextlib.asynccontextmanager
async def signal_stop_event(
    signals: tuple[signal.Signals, ...] = (signal.SIGTERM, signal.SIGINT),
):
    """Yield an asyncio.Event that is set when any listed signal is received.

    Handlers are installed on the running loop and always removed on exit, so
    this is safe to nest (e.g. in tests that spawn multiple workers in one
    process).
    """
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    installed: list[signal.Signals] = []
    for sig in signals:
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            # Non-Unix platforms, or another handler already owns the signal.
            continue
        installed.append(sig)
    try:
        yield stop
    finally:
        for sig in installed:
            with contextlib.suppress(NotImplementedError, RuntimeError, ValueError):
                loop.remove_signal_handler(sig)


async def run_service(
    *,
    serve: Callable[[], Awaitable[Any]],
    shutdown: Callable[[], Awaitable[Any]],
    ops_server: Any = None,
    grace_timeout: float = 30.0,
    signals: tuple[signal.Signals, ...] = (signal.SIGTERM, signal.SIGINT),
) -> None:
    """Run a service with signal-driven graceful shutdown.

    ``serve()`` is the main serving loop (it normally blocks until cancelled).
    ``shutdown()`` releases owned resources (consumers, producers, stores).
    ``ops_server`` is an optional ``shared.ops.server.OpsServer`` started before
    serving and stopped during shutdown. Exceptions raised by ``serve()`` are
    re-raised after cleanup so the process exits non-zero.
    """
    if ops_server is not None:
        await ops_server.start()
    async with signal_stop_event(signals=signals) as stop:
        main = asyncio.create_task(serve())
        waiter = asyncio.create_task(stop.wait())
        try:
            done, _ = await asyncio.wait(
                {main, waiter},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if main in done and main.exception() is not None:
                # A real failure — surface it below after cleanup.
                pass
        finally:
            waiter.cancel()
            failure: BaseException | None = None
            if main.done() and not main.cancelled():
                exc = main.exception()
                if exc is not None:
                    failure = exc
            if not main.done():
                main.cancel()
            await asyncio.gather(main, return_exceptions=True)
            if ops_server is not None:
                await ops_server.stop()
            try:
                await asyncio.wait_for(shutdown(), timeout=grace_timeout)
            except TimeoutError:
                logger.warning(
                    "graceful shutdown exceeded %ss and was abandoned",
                    grace_timeout,
                )
            if failure is not None:
                raise failure
