"""Document handlers for standalone ingestion."""

from ingestion_service.handlers.archive import ZipArchiveHandler
from ingestion_service.handlers.base import DocumentHandler
from ingestion_service.handlers.docling import DoclingDocumentHandler
from ingestion_service.handlers.docx import DocxNativeHandler
from ingestion_service.handlers.generic_markdown import MarkItDownHandler
from ingestion_service.handlers.html import HtmlDocumentHandler
from ingestion_service.handlers.markdown import MarkdownDocumentHandler
from ingestion_service.handlers.pdf_native import PdfNativeTextHandler
from ingestion_service.handlers.pptx import PptxNativeHandler
from ingestion_service.handlers.spreadsheet import CsvHandler, XlsxHandler
from ingestion_service.handlers.text import TextDocumentHandler

__all__ = [
    "CsvHandler",
    "DoclingDocumentHandler",
    "DocumentHandler",
    "DocxNativeHandler",
    "HtmlDocumentHandler",
    "MarkdownDocumentHandler",
    "MarkItDownHandler",
    "PdfNativeTextHandler",
    "PptxNativeHandler",
    "TextDocumentHandler",
    "XlsxHandler",
    "ZipArchiveHandler",
]
