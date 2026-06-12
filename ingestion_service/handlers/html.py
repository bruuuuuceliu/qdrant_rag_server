"""Low-cost HTML document handler."""

from __future__ import annotations

from html.parser import HTMLParser

from ingestion_service.normalization import normalize_text
from ingestion_service.schemas import (
    DocumentHandlingPolicy,
    HandlerOutput,
    IngestedDocument,
    IngestedSection,
    SourceBlob,
)


class HtmlDocumentHandler:
    name = "html"
    supported_content_types = ("text/html", "application/xhtml+xml")
    supported_extensions = (".html", ".htm")
    resource_tier = "minimal"

    async def parse(
        self,
        source: SourceBlob,
        *,
        policy: DocumentHandlingPolicy,
    ) -> HandlerOutput:
        del policy
        parser = _HTMLTextExtractor()
        parser.feed(source.text())
        text = normalize_text(parser.text())
        title = normalize_text(parser.title)
        document = IngestedDocument(
            document_id=source.document_id,
            source_uri=source.source_uri,
            content_type=source.content_type,
            data_type=source.data_type,
            content_hash=source.checksum,
            title=title,
            handler_name=self.name,
            metadata={**source.metadata, "raw_text": text, "title": title},
        )
        return HandlerOutput(
            document=document,
            sections=(
                IngestedSection(section_id="0", text=text or source.source_uri, order=0),
            ),
        )


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._in_title = False
        self._parts: list[str] = []
        self.title = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag in {"p", "div", "section", "article", "br", "li", "h1", "h2", "h3"}:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False
        if tag in {"p", "div", "section", "article", "li", "h1", "h2", "h3"}:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self.title += data
            return
        self._parts.append(data)

    def text(self) -> str:
        return " ".join(part.strip() for part in self._parts if part.strip())
