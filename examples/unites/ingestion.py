"""Standalone ingestion methods showcase.

Setup:
1. Install dependencies: ``python -m pip install -e .``
2. Optional: set ``INGESTION_SHOWCASE_HTTP_URL`` in ``examples/unites/.env``
   to try HTTP/HTTPS source loading.
3. Run: ``python -m examples.unites.ingestion``

This showcase exercises the standalone ingestion layer only. It does not need
Qdrant, embeddings, or generation credentials.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from ingestion_service import (  # noqa: E402
    DocumentHandlingPolicy,
    IngestionService,
    ResourceBudget,
    SourceDescriptor,
)

load_dotenv(Path(__file__).with_name(".env"))

EXAMPLE_FILES = Path(__file__).with_name("example_files")


async def main() -> None:
    service = IngestionService()

    await _showcase(
        service,
        "raw_text metadata",
        SourceDescriptor(
            source_uri="memory://raw-text",
            document_id="raw_text_doc",
            content_type="text/plain",
            metadata={
                "raw_text": "Standalone ingestion loads raw text directly.\n\n"
                "Short paragraphs are packed into bounded chunks."
            },
        ),
    )

    await _showcase(
        service,
        "raw_content metadata",
        SourceDescriptor(
            source_uri="memory://raw-content.md",
            document_id="raw_content_doc",
            content_type="text/markdown",
            filename="raw-content.md",
            metadata={
                "raw_content": b"# Raw content\n\nBytes can be routed as markdown."
            },
        ),
    )

    txt_path = EXAMPLE_FILES / "test_txt.txt"
    pdf_path = EXAMPLE_FILES / "test_pdf.pdf"
    docx_path = EXAMPLE_FILES / "test_doc.docx"

    await _showcase(
        service,
        "local TXT file path",
        SourceDescriptor(
            source_uri=str(txt_path),
            document_id="local_txt_doc",
            content_type="text/plain",
            filename=txt_path.name,
        ),
    )

    await _showcase(
        service,
        "local PDF file path",
        SourceDescriptor(
            source_uri=str(pdf_path),
            document_id="local_pdf_doc",
            content_type="application/pdf",
            filename=pdf_path.name,
        ),
        policy=DocumentHandlingPolicy(budget=ResourceBudget(max_pages=20)),
    )

    await _showcase(
        service,
        "local DOCX file path",
        SourceDescriptor(
            source_uri=str(docx_path),
            document_id="local_docx_doc",
            content_type=(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
            filename=docx_path.name,
        ),
    )

    await _showcase(
        service,
        "file URL",
        SourceDescriptor(
            source_uri=txt_path.as_uri(),
            document_id="file_url_txt_doc",
            content_type="text/plain",
            filename=txt_path.name,
        ),
    )

    await _showcase(
        service,
        "literal source_uri fallback",
        SourceDescriptor(
            source_uri="A source_uri with no matching file is ingested as plain text.",
            document_id="literal_uri_doc",
            content_type="text/plain",
        ),
    )

    http_url = os.getenv("INGESTION_SHOWCASE_HTTP_URL", "").strip()
    if http_url:
        await _showcase(
            service,
            "HTTP URL",
            SourceDescriptor(
                source_uri=http_url,
                document_id="http_url_doc",
                content_type="text/plain",
            ),
            policy=DocumentHandlingPolicy(allow_local_files=False),
        )


async def _showcase(
    service: IngestionService,
    label: str,
    source: SourceDescriptor,
    *,
    policy: DocumentHandlingPolicy | None = None,
) -> None:
    result = await service.process(source, policy=policy)
    document = result.document

    print(f"\n=== {label} ===")
    print(f"doc_id={document.document_id}")
    print(f"handler={result.route_decision.handler_name}")
    print(f"content_type={document.content_type}")
    print(f"raw_bytes={len(result.raw_content)}")
    print(f"cleaning={_cleaning_summary(result.cleaning.stats or {})}")
    print(f"chunks={len(result.chunks)}")
    for dropped in result.cleaning.dropped_sections[:3]:
        print(f"- dropped {dropped.section_id}: {dropped.reason}")
    shown_chunks = result.chunks[:5]
    for chunk in shown_chunks:
        text = chunk.text.replace("\n", " ")
        if len(text) > 180:
            text = f"{text[:177]}..."
        page_range = _page_range(chunk.metadata)
        page_label = f" pages={page_range}" if page_range else ""
        print(f"- {chunk.chunk_id}{page_label}: {text}")
    if len(result.chunks) > len(shown_chunks):
        omitted = len(result.chunks) - len(shown_chunks)
        print(f"... {omitted} more chunks")


def _cleaning_summary(stats: dict[str, object]) -> str:
    return (
        f"sections {stats.get('input_sections', 0)}->{stats.get('output_sections', 0)}, "
        f"dropped={stats.get('dropped_sections', 0)}, "
        f"removed_repeated_lines={stats.get('removed_repeated_lines', 0)}"
    )


def _page_range(metadata: dict[str, object]) -> str:
    start_page = metadata.get("start_page")
    end_page = metadata.get("end_page")
    if not start_page or not end_page:
        return ""
    if start_page == end_page:
        return str(start_page)
    return f"{start_page}-{end_page}"


if __name__ == "__main__":
    asyncio.run(main())
