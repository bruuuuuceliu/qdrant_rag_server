"""Test case 2: ingest raw text and poll job status through gRPC."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from examples.test_client.test_client import (
    RagTestClient,
    add_common_args,
    config_from_args,
    print_json,
    require_terminal_ingest_status,
)


DEFAULT_TEXT = (
    "Qdrant stores vector embeddings for semantic retrieval. "
    "This document was inserted by examples.test_client.test_2."
)


async def main() -> None:
    args = _parse_args()
    config = config_from_args(args)
    async with RagTestClient(config) as client:
        ingest_result = await client.ingest(
            doc_id=args.doc_id,
            text=args.text,
            source_uri=args.source_uri or _write_local_source(args.doc_id, args.text),
            content_type=args.content_type,
        )
        print_json({"ingest": ingest_result})

        job_id = ingest_result.get("job_id")
        if not job_id or args.no_wait:
            return

        status = await client.wait_for_ingest_status(
            str(job_id),
            poll_seconds=args.poll_seconds,
            max_attempts=args.max_attempts,
        )
        require_terminal_ingest_status(status)
        print_json({"status": status})


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_args(parser)
    parser.add_argument("--text", default=DEFAULT_TEXT)
    parser.add_argument("--source-uri", default=None)
    parser.add_argument("--content-type", default="text/plain")
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    parser.add_argument("--max-attempts", type=int, default=30)
    parser.add_argument("--no-wait", action="store_true")
    return parser.parse_args()


def _write_local_source(doc_id: str | None, text: str) -> str:
    safe_doc_id = "".join(
        char if char.isalnum() or char in {"-", "_"} else "_"
        for char in (doc_id or "test_client_doc")
    ).strip("_")
    source_dir = Path(".run/test_client").resolve()
    source_dir.mkdir(parents=True, exist_ok=True)
    source_path = source_dir / f"{safe_doc_id or 'test_client_doc'}.txt"
    source_path.write_text(text, encoding="utf-8")
    return str(source_path)


if __name__ == "__main__":
    asyncio.run(main())
