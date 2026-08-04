"""Broker-first manager process entrypoint."""

from __future__ import annotations

import asyncio

from configs import load_settings
from deployment.composition.manager import create_manager_context
from shared.logging import configure_logging
from shared.ops.server import ops_server_from_env
from shared.ops.shutdown import run_service
from shared.runtime_health import RuntimeHealth


async def serve_forever() -> None:
    context = await create_manager_context(load_settings())

    async def readiness() -> RuntimeHealth:
        return RuntimeHealth(
            service="manager_service",
            ready=True,
            dependencies={
                "grpc_server": context.server is not None,
                "task_producer": context.task_producer is not None,
                "task_status_store": context.task_status_store is not None,
            },
        )

    ops_server = ops_server_from_env("manager_service", default_port=9001, readiness=readiness)
    await run_service(
        serve=lambda: context.server.wait_for_termination(),
        shutdown=context.shutdown,
        ops_server=ops_server,
    )


def main() -> None:
    configure_logging()
    asyncio.run(serve_forever())


if __name__ == "__main__":
    main()
