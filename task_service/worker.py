"""Task service process entrypoint."""

from __future__ import annotations

import asyncio

from deployment.composition.task_service import create_task_service_context
from shared.logging import configure_logging
from shared.ops.server import ops_server_from_env
from shared.ops.shutdown import run_service


async def serve_forever() -> None:
    context = create_task_service_context()
    ops_server = ops_server_from_env("task_service", default_port=9003, readiness=context.health)

    async def serve() -> None:
        await context.start_runtime()
        while True:
            await asyncio.sleep(3600)

    await run_service(serve=serve, shutdown=context.stop, ops_server=ops_server)


def main() -> None:
    configure_logging()
    asyncio.run(serve_forever())


if __name__ == "__main__":
    main()
