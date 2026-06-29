"""Test case 4: make an HTTP POST /search call to the retrieval API."""

from __future__ import annotations

import argparse
import asyncio
import json

from examples.test_client.test_client import (
    RagTestClient,
    add_common_args,
    config_from_args,
    print_json,
    require_http_envelope,
)


async def main() -> None:
    args = _parse_args()
    config = config_from_args(args)
    retrieval_config = json.loads(args.retrieval_config)
    if not isinstance(retrieval_config, dict):
        raise ValueError("--retrieval-config must be a JSON object")

    async with RagTestClient(config) as client:
        result = await client.post_search(
            query=args.query,
            request_id=args.request_id,
            retrieval_config=retrieval_config,
        )
        require_http_envelope(result)
        chunks = result.get("result", {}).get("chunks")
        if args.require_chunks and not chunks:
            raise RuntimeError(f"HTTP search returned no chunks: {result}")
        print_json(result)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_args(parser)
    parser.add_argument(
        "--query",
        default="What does Qdrant store for semantic retrieval?",
    )
    parser.add_argument("--request-id", default=None)
    parser.add_argument("--retrieval-config", default='{"top_k": 5}')
    parser.add_argument(
        "--allow-empty",
        dest="require_chunks",
        action="store_false",
        help="Allow a valid HTTP search response with zero chunks.",
    )
    parser.set_defaults(require_chunks=True)
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(main())
