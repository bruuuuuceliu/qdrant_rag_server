"""Test case 3: run a gRPC search against a local or remote RAG server."""

from __future__ import annotations

import argparse
import asyncio

from examples.test_client.test_client import (
    RagTestClient,
    add_common_args,
    config_from_args,
    print_json,
    require_search_response,
)


async def main() -> None:
    args = _parse_args()
    config = config_from_args(args)
    async with RagTestClient(config) as client:
        result = await client.search(
            query=args.query,
            kb_ids=tuple(args.kb_id_list or (config.kb_id,)),
            include_shared=config.include_shared,
        )
        require_search_response(result, require_chunks=args.require_chunks)
        print_json(result)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_args(parser)
    parser.add_argument(
        "--query",
        default="What does Qdrant store for semantic retrieval?",
    )
    parser.add_argument(
        "--kb-id-list",
        action="append",
        default=None,
        help="Repeat to pass multiple kb_ids. Defaults to --kb-id/RAG_TEST_KB_ID.",
    )
    parser.add_argument(
        "--allow-empty",
        dest="require_chunks",
        action="store_false",
        help="Allow a valid search response with zero chunks.",
    )
    parser.set_defaults(require_chunks=True)
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(main())
