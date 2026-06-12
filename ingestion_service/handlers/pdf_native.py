"""Native text extraction handler for digital PDFs."""

from __future__ import annotations

from tempfile import NamedTemporaryFile

from ingestion_service.errors import NeedsDoclingConversion, ParseError
from ingestion_service.normalization import normalize_text
from ingestion_service.schemas import (
    DocumentHandlingPolicy,
    HandlerOutput,
    IngestedDocument,
    IngestedSection,
    SourceBlob,
)


class PdfNativeTextHandler:
    name = "pdf_native_text"
    supported_content_types = ("application/pdf",)
    supported_extensions = (".pdf",)
    resource_tier = "minimal"

    async def parse(
        self,
        source: SourceBlob,
        *,
        policy: DocumentHandlingPolicy,
    ) -> HandlerOutput:
        text_by_page = _extract_with_pymupdf(source.content, max_pages=policy.budget.max_pages)
        if text_by_page is None:
            text_by_page = _extract_with_pypdf(source.content, max_pages=policy.budget.max_pages)
        if text_by_page is None:
            raise ParseError("PDF text extraction requires PyMuPDF or pypdf")
        sections = [
            IngestedSection(
                section_id=str(index),
                text=normalize_text(text),
                order=index,
                page_number=index + 1,
            )
            for index, text in enumerate(text_by_page)
            if normalize_text(text)
        ]
        if not sections:
            raise NeedsDoclingConversion("PDF has no extractable text layer")
        document = IngestedDocument(
            document_id=source.document_id,
            source_uri=source.source_uri,
            content_type=source.content_type,
            data_type=source.data_type,
            content_hash=source.checksum,
            handler_name=self.name,
            metadata={**source.metadata, "page_count": len(text_by_page)},
        )
        return HandlerOutput(document=document, sections=tuple(sections))


def _extract_with_pymupdf(content: bytes, *, max_pages: int) -> list[str] | None:
    try:
        import fitz  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        return None
    with NamedTemporaryFile(suffix=".pdf") as temp:
        temp.write(content)
        temp.flush()
        doc = fitz.open(temp.name)
        try:
            return [page.get_text("text") for page in doc[:max_pages]]
        finally:
            doc.close()


def _extract_with_pypdf(content: bytes, *, max_pages: int) -> list[str] | None:
    try:
        from pypdf import PdfReader  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        return None
    from io import BytesIO

    reader = PdfReader(BytesIO(content))
    return [page.extract_text() or "" for page in reader.pages[:max_pages]]
