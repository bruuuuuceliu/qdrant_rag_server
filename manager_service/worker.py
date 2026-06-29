"""Broker-first manager process entrypoint."""

from __future__ import annotations

import asyncio

from configs import load_settings
from deployment.composition.manager import create_manager_context
from shared.logging import configure_logging


async def serve_forever() -> None:
    context = await create_manager_context(load_settings())
    try:
        await context.server.wait_for_termination()
    finally:
        await context.shutdown()


def main() -> None:
    configure_logging()
    asyncio.run(serve_forever())


if __name__ == "__main__":
    main()
