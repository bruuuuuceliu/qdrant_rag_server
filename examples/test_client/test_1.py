"""Test case 1: gRPC health check against a local or remote RAG server."""

from __future__ import annotations

import asyncio

from examples.test_client.test_client import (
    RagTestClient,
    config_from_args,
    parse_common_args,
    print_json,
    require_health_response,
)


async def main() -> None:
    args = parse_common_args("Run a gRPC HealthCheck request")
    config = config_from_args(args)
    async with RagTestClient(config) as client:
        result = await client.health()
        require_health_response(result)
        print_json(result)


if __name__ == "__main__":
    asyncio.run(main())
