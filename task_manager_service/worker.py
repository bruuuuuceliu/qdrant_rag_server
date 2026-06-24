"""Task manager process entrypoint."""

from __future__ import annotations

import asyncio

from deployment.composition.task_manager import create_task_manager_context


async def serve_forever() -> None:
    context = create_task_manager_context()
    context.start()
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await context.stop()


def main() -> None:
    asyncio.run(serve_forever())


if __name__ == "__main__":
    main()
