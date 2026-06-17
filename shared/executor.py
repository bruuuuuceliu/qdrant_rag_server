"""Thread-pool executor for offloading blocking I/O from async event loops.

SQLite, filesystem, and other synchronous operations run through this
executor so they don't stall the asyncio event loop.

Use AsyncExecutor per application scope; do not share across event loops.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any, Callable, TypeVar

T = TypeVar("T")


class AsyncExecutor:
    """Runs blocking callables on a dedicated thread pool."""

    def __init__(self, *, max_workers: int = 4) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers)

    async def run(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        loop = asyncio.get_running_loop()
        call = partial(fn, *args, **kwargs) if args or kwargs else fn
        return await loop.run_in_executor(self._executor, call)

    def shutdown(self, *, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait)
