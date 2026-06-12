"""Safe ZIP archive handler."""

from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

from ingestion_service.errors import ParseError, SourceTooLargeError
from ingestion_service.schemas import (
    DocumentHandlingPolicy,
    HandlerOutput,
    IngestedDocument,
    IngestedSection,
    SourceBlob,
)


class ZipArchiveHandler:
    name = "zip_archive"
    supported_content_types = ("application/zip",)
    supported_extensions = (".zip",)
    resource_tier = "minimal"

    async def parse(
        self,
        source: SourceBlob,
        *,
        policy: DocumentHandlingPolicy,
    ) -> HandlerOutput:
        with ZipFile(BytesIO(source.content)) as archive:
            infos = archive.infolist()
            if len(infos) > 1000:
                raise SourceTooLargeError("archive contains too many files")
            total_size = sum(info.file_size for info in infos)
            if total_size > policy.budget.max_source_bytes * 5:
                raise SourceTooLargeError("archive expansion ratio exceeds policy")
            names = [
                info.filename
                for info in infos
                if not info.is_dir() and not _unsafe_archive_path(info.filename)
            ]
        if not names:
            raise ParseError("archive contains no safe files")
        document = IngestedDocument(
            document_id=source.document_id,
            source_uri=source.source_uri,
            content_type=source.content_type,
            data_type=source.data_type,
            content_hash=source.checksum,
            handler_name=self.name,
            metadata={**source.metadata, "archive_file_count": len(names)},
        )
        return HandlerOutput(
            document=document,
            sections=(
                IngestedSection(
                    section_id="archive",
                    text="\n".join(names),
                    order=0,
                    metadata={"archive_listing": True},
                ),
            ),
        )


def _unsafe_archive_path(path: str) -> bool:
    return path.startswith("/") or ".." in path.split("/")
