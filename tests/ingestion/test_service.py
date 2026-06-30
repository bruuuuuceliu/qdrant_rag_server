"""Standalone ingestion package tests."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ingestion_service import (
    CleaningPolicy,
    DocumentHandlingPolicy,
    DocumentCleaner,
    IngestedDocument,
    IngestedSection,
    IngestionService,
    NeedsDoclingConversion,
    SourceDescriptor,
)
from ingestion_service.chunking import SectionAwareChunker
from ingestion_service.routing import FileRouter
from ingestion_service.source import load_source


class SourceLoadingTest(unittest.IsolatedAsyncioTestCase):
    async def test_loads_raw_text_metadata(self) -> None:
        source = await load_source(
            SourceDescriptor(
                source_uri="memory://doc",
                document_id="d1",
                metadata={"raw_text": "Hello\n\nWorld"},
            )
        )

        self.assertEqual(source.text(), "Hello\n\nWorld")
        self.assertEqual(source.document_id, "d1")
        self.assertTrue(source.checksum)

    async def test_loads_top_level_raw_text_request(self) -> None:
        source = await load_source(
            {
                "project_id": "p1",
                "user_id": "u1",
                "kb_id": "kb",
                "doc_id": "d1",
                "source_uri": "memory://doc",
                "content_type": "text/plain",
                "raw_text": "Top level raw text",
            }
        )

        self.assertEqual(source.text(), "Top level raw text")
        self.assertEqual(source.metadata["raw_text"], "Top level raw text")

    async def test_loads_top_level_raw_content_request(self) -> None:
        source = await load_source(
            {
                "project_id": "p1",
                "user_id": "u1",
                "kb_id": "kb",
                "doc_id": "d1",
                "source_uri": "memory://doc",
                "content_type": "text/plain",
                "raw_content": b"Top level bytes",
            }
        )

        self.assertEqual(source.content, b"Top level bytes")
        self.assertEqual(source.metadata["raw_content"], b"Top level bytes")

    async def test_loads_local_file_when_allowed(self) -> None:
        with TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "doc.txt"
            path.write_text("file text", encoding="utf-8")
            source = await load_source(
                SourceDescriptor(source_uri=str(path), document_id="d1")
            )

        self.assertEqual(source.text(), "file text")
        self.assertEqual(source.content_type, "text/plain")


class FileRouterTest(unittest.TestCase):
    def test_routes_markdown_by_extension(self) -> None:
        source = _source("doc.md", content_type="application/octet-stream")
        routed = FileRouter().route(source, policy=DocumentHandlingPolicy())

        self.assertEqual(routed.decision.handler_name, "markdown")

    def test_docling_route_raises_escalation_when_enabled_without_minimal_handler(self) -> None:
        source = _source("image.png", content_type="image/png")

        with self.assertRaises(NeedsDoclingConversion):
            FileRouter().route(
                source,
                policy=DocumentHandlingPolicy(allow_docling=True),
            )


class IngestionServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_processes_raw_text_into_chunks(self) -> None:
        result = await IngestionService().process(
            SourceDescriptor(
                source_uri="memory://doc",
                document_id="d1",
                metadata={"raw_text": "First\n\nSecond"},
            )
        )

        self.assertEqual(result.document.document_id, "d1")
        self.assertEqual([chunk.text for chunk in result.chunks], ["First\n\nSecond"])
        self.assertEqual(result.route_decision.handler_name, "text")

    async def test_processes_mapping_request_raw_text_into_chunks(self) -> None:
        result = await IngestionService().process(
            {
                "source_uri": "memory://doc",
                "content_type": "text/plain",
                "doc_id": "d1",
                "raw_text": "First\n\nSecond",
                "metadata": {"data_type": "project_document"},
            }
        )

        self.assertEqual(result.document.document_id, "d1")
        self.assertEqual([chunk.text for chunk in result.chunks], ["First\n\nSecond"])
        self.assertEqual(result.raw_content, b"First\n\nSecond")

    async def test_cleaning_metadata_reaches_chunks(self) -> None:
        result = await IngestionService().process(
            SourceDescriptor(
                source_uri="memory://doc",
                document_id="d1",
                metadata={"raw_text": "First line\nSecond line"},
            )
        )

        self.assertTrue(result.cleaning.stats["cleaning_enabled"])
        self.assertEqual(result.chunks[0].metadata["cleaning_version"], "v1")
        self.assertTrue(result.chunks[0].metadata["cleaning_applied"])


class DocumentCleanerTest(unittest.TestCase):
    def test_removes_repeated_page_edge_lines_and_preserves_pages(self) -> None:
        result = DocumentCleaner().clean(
            (
                IngestedSection(
                    section_id="p1",
                    text="CONFIDENTIAL\n\nFirst body text",
                    order=0,
                    page_number=1,
                ),
                IngestedSection(
                    section_id="p2",
                    text="CONFIDENTIAL\n\nSecond body text",
                    order=1,
                    page_number=2,
                ),
                IngestedSection(
                    section_id="p3",
                    text="CONFIDENTIAL\n\nThird body text",
                    order=2,
                    page_number=3,
                ),
            ),
            policy=CleaningPolicy(repeated_line_min_pages=3),
        )

        self.assertEqual(len(result.sections), 3)
        self.assertNotIn("CONFIDENTIAL", result.sections[0].text)
        self.assertEqual(result.sections[0].page_number, 1)
        self.assertEqual(result.sections[0].metadata["removed_repeated_lines"], 1)
        self.assertEqual(result.stats["removed_repeated_lines"], 3)

    def test_drops_empty_sections_with_audit_record(self) -> None:
        result = DocumentCleaner().clean(
            (
                IngestedSection(section_id="empty", text="\x00\n\n", order=0),
                IngestedSection(section_id="body", text="Useful content for indexing", order=1),
            ),
            policy=CleaningPolicy(),
        )

        self.assertEqual([section.section_id for section in result.sections], ["body"])
        self.assertEqual(result.dropped_sections[0].section_id, "empty")
        self.assertEqual(result.dropped_sections[0].reason, "empty")


class SectionAwareChunkerTest(unittest.TestCase):
    def test_packs_sections_and_preserves_page_range_metadata(self) -> None:
        chunks = SectionAwareChunker(max_chars=30).chunk(
            IngestedDocument(document_id="d1", source_uri="memory://doc"),
            (
                IngestedSection(section_id="p1", text="First page", order=0, page_number=1),
                IngestedSection(section_id="p2", text="Second page", order=1, page_number=2),
                IngestedSection(section_id="p3", text="Third page", order=2, page_number=3),
            ),
        )

        self.assertEqual([chunk.text for chunk in chunks], ["First page\n\nSecond page", "Third page"])
        self.assertEqual(chunks[0].metadata["start_page"], 1)
        self.assertEqual(chunks[0].metadata["end_page"], 2)
        self.assertNotIn("page_number", chunks[0].metadata)
        self.assertEqual(chunks[1].metadata["start_page"], 3)
        self.assertEqual(chunks[1].metadata["end_page"], 3)
        self.assertEqual(chunks[1].metadata["page_number"], 3)


def _source(source_uri: str, *, content_type: str = "text/plain"):
    from ingestion_service import SourceBlob

    return SourceBlob(
        source_uri=source_uri,
        content=b"content",
        content_type=content_type,
        document_id="d1",
        checksum="hash",
    )


if __name__ == "__main__":
    unittest.main()
