"""Markdown document handler."""

from __future__ import annotations

from ingestion_service.normalization import normalize_text
from ingestion_service.schemas import (
    DocumentHandlingPolicy,
    HandlerOutput,
    IngestedDocument,
    IngestedSection,
    SourceBlob,
)


class MarkdownDocumentHandler:
    name = "markdown"
    supported_content_types = ("text/markdown", "text/x-markdown")
    supported_extensions = (".md", ".markdown")
    resource_tier = "minimal"

    async def parse(
        self,
        source: SourceBlob,
        *,
        policy: DocumentHandlingPolicy,
    ) -> HandlerOutput:
        del policy
        text = normalize_text(source.text())
        sections = _markdown_sections(text)
        document = IngestedDocument(
            document_id=source.document_id,
            source_uri=source.source_uri,
            content_type=source.content_type,
            data_type=source.data_type,
            content_hash=source.checksum,
            title=_first_heading(text),
            handler_name=self.name,
            metadata={**source.metadata, "raw_text": text},
        )
        return HandlerOutput(document=document, sections=tuple(sections))


def _markdown_sections(text: str) -> list[IngestedSection]:
    sections: list[IngestedSection] = []
    heading = ""
    lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("#") and line.lstrip("#").startswith(" "):
            if lines:
                sections.append(
                    IngestedSection(
                        section_id=str(len(sections)),
                        text="\n".join(lines).strip(),
                        heading=heading,
                        order=len(sections),
                    )
                )
                lines = []
            heading = line.lstrip("#").strip()
        else:
            lines.append(line)
    if lines or not sections:
        sections.append(
            IngestedSection(
                section_id=str(len(sections)),
                text="\n".join(lines).strip() or text,
                heading=heading,
                order=len(sections),
            )
        )
    return sections


def _first_heading(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("#") and line.lstrip("#").startswith(" "):
            return line.lstrip("#").strip()
    return ""
