"""Test case 5: make an HTTP POST /documents/raw call to the retrieval API."""

from __future__ import annotations

import argparse
import asyncio

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
    async with RagTestClient(config) as client:
        result = await client.post_raw_document(
            doc_id=args.doc_id,
            request_id=args.request_id,
        )
        require_http_envelope(result)
        raw_result = result.get("result", {})
        if args.require_found and raw_result.get("found") is not True:
            raise RuntimeError(f"raw document was not found: {result}")
        print_json(result)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_args(parser)
    parser.add_argument("--request-id", default=None)
    parser.add_argument(
        "--allow-missing",
        dest="require_found",
        action="store_false",
        help="Allow a valid raw-document response with found=false.",
    )
    parser.set_defaults(require_found=True)
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(main())
