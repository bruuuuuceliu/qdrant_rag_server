"""Task service process entrypoint."""

from __future__ import annotations

import asyncio

from deployment.composition.task_service import create_task_service_context
from shared.logging import configure_logging


async def serve_forever() -> None:
    context = create_task_service_context()
    await context.start_runtime()
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await context.stop()


def main() -> None:
    configure_logging()
    asyncio.run(serve_forever())


if __name__ == "__main__":
    main()
